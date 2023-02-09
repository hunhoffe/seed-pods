from __future__ import annotations
from hashlib import md5
from seedemu.core import Node, NodeFile, NodeSoftware, NodeSoftwareInstaller
from typing import List

SEEDEMU_CLIENT_IMAGE='handsonsecurity/seedemu-map'

DockerImageFileTemplates: Dict[str, str] = {}

DockerImageFileTemplates['dockerfile_start'] = """\
ARG DEBIAN_FRONTEND=noninteractive
RUN echo 'exec zsh' > /root/.bashrc
"""

class DockerImage(object):
    """!
    @brief The DockerImage class.

    This class repersents a candidate image for docker compiler.
    """
    __software: List[NodeSoftware]
    __name: str
    __local: bool
    __dirName: str
    __baseImage: DockerImage
    __packageInstallTiers:  List[List[NodeSoftware]]

    def __init__(self, name: str, software: List[NodeSoftware], local: bool = False, dirName: str = None, baseImage: DockerImage = None) -> None:
        """!
        @brief create a new docker image.

        @param name name of the image. Can be name of a local image, image on
        dockerhub, or image in private repo.
        @param software set of software pre-installed in the image, so the
        docker compiler can skip them when compiling.
        @param local (optional) set this image as a local image. A local image
        is built locally instead of pulled from the docker hub. Default to False.
        @param dirName (optional) directory name of the local image (when local
        is True). Default to None. None means use the name of the image.
        @param baseImage (optional) Name of image to build on top of
        """
        if not local:
            assert baseImage is None, "Remote images cannot have a base image"

        super().__init__()

        self.__name = name
        self.__software = []
        self.__local = local
        self.__dirName = dirName if dirName != None else name
        self.__baseImage = baseImage
        self.__packageInstallTiers = None

        baseSoftware = []
        if self.__baseImage:
            baseSoftware = self.__baseImage.getSoftware()

        for soft in software:
            if soft not in baseSoftware:
                self.__software.append(soft)

    def getName(self) -> str:
        """!
        @brief get the name of this image.

        @returns name.
        """
        return self.__name

    def getSoftware(self) -> List[NodeSoftware]:
        """!
        @brief get set of software installed on this image.
        
        @return set.
        """
        return self.__software
    
    def addSoftware(self, soft: NodeSoftware) -> DockerImage:
        """!
        @brief add to the set of software installed on this image.
        
        @returns self, for chaining api calls.
        """
        baseSoftware = []
        if self.__baseImage:
            baseSoftware = self.__baseImage.getSoftware()

        if soft not in baseSoftware:
            self.__software.append(soft)

        return self

    def getDirName(self) -> str:
        """!
        @brief returns the directory name of this image.

        @return directory name.
        """
        return self.__dirName
    
    def isLocal(self) -> bool:
        """!
        @brief returns True if this image is local.

        @return True if this image is local.
        """
        return self.__local

    def setSoftwareInstallTiers(self, tiers: List[List[NodeSoftware]]) -> DockerImage:
        """!
        @brief returns Groupings for software installed with a package installer

        @returns self, for chaining api calls.
        """
        self.__packageInstallTiers = tiers
        return self

    def generateImageSetup(self):
        """!
        @brief Generate a docker file for the current docker image

        @returns dockerfile contents
        """
        dockerfile = ""

        # Create from base image, if has base image
        if self.__baseImage:
            dockerfile += "# The base image of the DockerImage\n"
            if not self.__baseImage.isLocal():
                # Use dummy name for remote images
                dockerfile += f"FROM {md5(self.__baseImage.getName().encode('utf-8')).hexdigest()}\n"
            else:
                # Use actual name for local images
                dockerfile += f"FROM {self.__baseImage.getName()}\n"

        dockerfile += '\n# Default dockerfile commands used for all SEED docker images\n'
        dockerfile += DockerImageFileTemplates['dockerfile_start']

        # Without this line, we get 'apt package config delayed' warnings, or something like that
        dockerfile += '\n# Setup apt-get and update accordingly\n'
        dockerfile += 'RUN apt-get update && apt-get install -y --no-install-recommends apt-utils\n'

        # Install software via package manager
        softPackages = set([s.name for s in self.__software if s.usePackageManager()])
        if len(softPackages) > 0:
            use_software_tiers = not (self.__packageInstallTiers is None)
            dockerfile += f"\n# Installing software with package manager (software_tiers={use_software_tiers})\n"
            if use_software_tiers:
                installedSoft = set()
                for tier in self.__packageInstallTiers:
                    packages = [pkg.name for pkg in tier]
                    dockerfile += 'RUN apt-get update && apt-get install -y --no-install-recommends {}\n'.format(' '.join(sorted(set(packages))))
                    installedSoft |= set(packages)
                toInstall = [s for s in softPackages if not (s in installedSoft)]
                if len(toInstall) > 0:
                    dockerfile += '\n# Installing leftover software packages after installing all tiers\n'
                    dockerfile += 'RUN apt-get update && apt-get install -y --no-install-recommends {}\n'.format(' '.join(sorted(set(toInstall))))
            else:
                dockerfile += 'RUN apt-get update && apt-get install -y --no-install-recommends {}\n'.format(' '.join(sorted(softPackages)))

        # Install software that is installed via script
        softScripts = [s for s in self.__software if not s.usePackageManager()]
        if len(softScripts) > 0:
            dockerfile += "\n# Installing software via script\n"
            for s in softScripts:
                dockerfile += self.__runFile(s.installScript)

        # If parent image has cmd, it's okay - docker will override it and use this.
        dockerfile += '\n# Command that runs when a container based on this image is instantiated\n'

        dockerfile += 'CMD ["/start.sh"]\n'
        print(dockerfile, file=open('Dockerfile', 'w'))

    def rebaseImage(self, baseImage: DockerImage) -> DockerImage:
        """!
        @brief Create a new docker image with FROM baseImage with any additional dependencies (software, files) from self added. 

        @param baseImage the new base for the docker image

        @returns rebasedImage the new docker image.
        """
        rebasedImage = DockerImage(self.getName(), [], local=True, dirName=self.getDirName(), baseImage=baseImage)

        # Go through all fields and add anything not included in self.
        for s in self.getSoftware():
            if not (s in baseImage.getSoftware()):
                rebasedImage.addSoftware(s)
        
        # Only include tiers that install software the new rebased image needs
        if self.__packageInstallTiers:
            tiers = []
            for tier in self.__packageInstallTiers:
                new_tier = tier.intersection(rebasedImage.getSoftware())
                if len(new_tier) > 0:
                    tiers.append(tier)
        rebasedImage.setSoftwareInstallTiers(tiers)

        return rebasedImage

    def __runFile(cls, file: NodeFile) -> str:
        """!
        @brief Add the file to docker and add related commands to dockerfile string.

        @param file the file to add to the container image
        @param executeFile whether the execute the file or not (e.g., as in a script)

        @returns dockerfile commands.
        """
        stagedPath = md5(file.getPath().encode('utf-8')).hexdigest()
        if not (file.getHostPath() is None):
            copyfile(file.getHostPath(), stagedPath)
        else:
            content = file.getContent()
            if content is None:
                content = ''
            print(content, file=open(stagedPath, 'w'))

        dockerfile = f'COPY {stagedPath} {file.getPath()}\n'
        dockerfile += f'RUN chmod +x {file.getPath()}\n'
        dockerfile += f'RUN .{file.getPath()}\n'
        return dockerfile

    def __str__(self) -> str:
        base_image_name = None
        if self.__baseImage:
            base_image_name = self.__baseImage.getName()
        return f'DockerImage name={self.getName()}, local={self.isLocal()}, dirName={self.getDirName()} ' \
            f'baseImage={base_image_name}\ninstallTiers={self.__packageInstallTiers}\nsoftware={self.getSoftware()}'

DefaultImages: List[DockerImage] = []

DefaultImages.append(DockerImage('ubuntu:20.04', [], local=False))