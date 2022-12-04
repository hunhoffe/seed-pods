import re
import yaml
import json
import os.path
from typing import Dict, List

KubernetesCompilerFileTemplates: Dict[str, str] = {}

KubernetesCompilerFileTemplates['network'] = """\
apiVersion: "k8s.cni.cncf.io/v1"
kind: NetworkAttachmentDefinition
metadata:
  name: {networkName}
  namespace: {namespace}
spec:
  config: '{{
      "cniVersion": "0.3.0",
      "type": "macvlan",
      "master": "{interface}",
      "mode": "bridge",
      "ipam": {{
        "type": "static"
      }}
    }}'
"""

KubernetesCompilerFileTemplates['service'] = """\
apiVersion: v1
kind: Pod
metadata:
  name: name
  namespace: namespace
  labels: {}
  annotations:
    k8s.v1.cni.cncf.io/networks: networks
spec:
  containers:
  - image: image_name
    name: container_name
    resources: {}
    securityContext:
      capabilities:
        add:
        - ALL
      privileged: true
    imagePullPolicy: Never
"""

BaseImageName = "cfee3a34e9c68ac1d16035a81a926786"
NetworkLabelPrefix = "org.seedsecuritylabs.seedemu.meta.net"
NetworkMaskLabelTemplate = "org.seedsecuritylabs.seedemu.meta.net.{}.mask"
RoleLabel = "org.seedsecuritylabs.seedemu.meta.role"
ClassLabel = "org.seedsecuritylabs.seedemu.meta.class"
AsnLabel = "org.seedsecuritylabs.seedemu.meta.asn"

def getCompatibleName(name: str) -> str:
        return name.replace('_', '-').replace('.','-').replace(' ', '-')

def getYamlFileName(name: str) -> str:
        return getCompatibleName(name) + '.yml'

def getAlphaNumeric(string: str) -> str:
        return re.sub(r'\W+', '', string)

def isNetworkLabel(label: str) -> bool:
    return label.startswith(NetworkLabelPrefix)

def isRoleLabel(label: str) -> bool:
    return label == RoleLabel

def isClassLabel(label: str) -> bool:
    return label.startswith(ClassLabel)

def getNetworkNameFromLabel(label: str) -> str:
    return label.split('.')[5]

def isNetworkAddressLabel(label: str) -> bool:
    return isNetworkLabel(label) and label.split('.')[6] == "address"

def isNetworkNameLabel(label: str) -> bool:
    return isNetworkLabel(label) and label.split('.')[6] == "name"

class ServiceTemplate(object):
    __template: str

    def __init__(self) -> None:
        self.__template = yaml.load(KubernetesCompilerFileTemplates['service'], Loader=yaml.FullLoader)

    def setObjectName(self, name: str) -> None:
        self.__template['metadata']['name'] = name

    def setNamespace(self, namespace: str) -> None:
        self.__template['metadata']['namespace'] = namespace

    def setImageName(self, imageName) -> None:
        self.__template['spec']['containers'][0]['image'] = imageName

    def setContainerName(self, containerName) -> None:
        self.__template['spec']['containers'][0]['name'] = containerName

    def addLabel(self, label_name: str, label_value: str) -> None:
        self.__template['metadata']['labels'][label_name] = label_value

    def setNetworkMaskLabel(self, networkName: str, networkMask: str) -> None:
        self.__template['metadata']['labels'][NetworkMaskLabelTemplate.format(networkName)] = networkMask

    def setNetworkAnnotations(self, networkAnnotations: str) -> None:
        self.__template['metadata']['annotations']['k8s.v1.cni.cncf.io/networks'] = networkAnnotations

    def getYamlFile(self) -> str:
        return yaml.dump(self.__template, sort_keys=False)

class Kubernetes(object):

    __docker_files_path: str
    __docker_compose_file: str
    __namespace: str
    __interface: str
    __files: Dict[str, str]
    __project_name: str

    def __init__(self, dockerFilesPath: str = './output', namespace: str = 'seed', interface: str = 'eth0') -> None:
        self.__docker_files_path = dockerFilesPath
        self.__namespace = namespace
        self.__interface = interface
        self.__files = {}
        self.__project_name = os.path.basename(dockerFilesPath)
        try:
            with open(os.path.join(self.__docker_files_path, 'docker-compose.yml'), 'r') as file:
                self.__docker_compose_file = yaml.load(file, Loader=yaml.FullLoader)
        except Exception as e:
            raise Exception('Error opening the docker compose file: {}')

    def parseNetworks(self) -> None:
        for network in self.__docker_compose_file['networks']:
            self.__files[getYamlFileName(network)] = KubernetesCompilerFileTemplates['network'].format(
                networkName = getCompatibleName(network), 
                namespace = self.__namespace, 
                interface = self.__interface)

    def getNetworkAnnotations(self, networks: Dict[str, List[str]], namespace: str, asn: str, isRouter: bool = False) -> str:
        annotations = []
        for _, network in networks.items():
            net = {}
            net['namespace'] = namespace
            net['interface'] = network[0]
            if network[0].startswith('ix'):
                net['name'] = 'net-ix-{}'.format(getCompatibleName(network[0]))
            elif network[0].startswith('000'):
                net['name'] = getCompatibleName(network[0])
            else:
                net['name'] = 'net-{}-{}'.format(asn, getCompatibleName(network[0]))
            net['ips'] = [network[1]]
            if not isRouter:
                net['default-route'] = ['.'.join(network[1].split('/')[0].split('.')[:-1]) + '.254']
            annotations.append(net)
        return json.dumps(annotations, separators=(',', ':'))

    def parseServices(self) -> None:
        for service_name in self.__docker_compose_file['services']:
            if service_name != BaseImageName:
                service = self.__docker_compose_file['services'][service_name]
                template = ServiceTemplate()
                template.setObjectName(getCompatibleName(service_name))
                template.setNamespace(self.__namespace)
                template.setImageName('{}-{}'.format(self.__project_name, service_name))
                template.setContainerName(getCompatibleName(service['container_name']))
                
                networks = {}
                is_router = False
                for label in service['labels']:
                    label_value = service['labels'][label]
                    if isNetworkLabel(label):
                        network_name = getNetworkNameFromLabel(label)
                        if isNetworkNameLabel(label):
                            networks[network_name] = [label_value, None]
                        elif isNetworkAddressLabel(label):
                            networks[network_name][1] = label_value
                            mask = label_value.split('/')[1]
                            label_value = label_value.split('/')[0]
                            template.setNetworkMaskLabel(network_name, mask)
                    elif isRoleLabel(label):
                        label_value = getCompatibleName(label_value)
                        if label_value.startswith('Route'):
                            is_router = True
                    elif isClassLabel(label):
                        label_value = getAlphaNumeric(label_value)
                    template.addLabel(label, label_value)

                template.setNetworkAnnotations(self.getNetworkAnnotations(networks, self.__namespace, service['labels'][AsnLabel], is_router))
                self.__files[getYamlFileName(service_name)] = template.getYamlFile()

    def compile(self) -> None:
        self.parseNetworks()
        self.parseServices()
        output_directory = os.path.join(self.__docker_files_path, 'k8s')
        template_directory = os.path.join(output_directory, 'templates')
        os.makedirs(template_directory, exist_ok = True)
        for filename, data in self.__files.items():
            with open(os.path.join(template_directory, filename), 'w') as file:
                file.write(data)
