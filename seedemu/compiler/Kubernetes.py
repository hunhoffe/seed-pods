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

def isNetworkInterfaceLabel(label: str) -> bool:
    return isNetworkLabel(label) and label.split('.')[6] == "name"

def isExchange(interface: str) -> bool:
    return interface.startswith('ix')

def isServiceNetwork(interface: str) -> bool:
    return interface == "000_svc"

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

class NetworkAnnotations(object):
    __annotations: Dict[str, Dict[str, str]]

    def __init__(self) -> None:
        self.__annotations = {}

    def addNetworkAnnotation(self, name:str, interface: str, namespace: str) -> None:
        annotation = {}
        annotation['interface'] = interface
        annotation['namespace'] = namespace
        self.__annotations[name] = annotation

    def addIpAddress(self, name: str, ipAddress: str) -> None:
        annotation = self.__annotations[name]
        if 'ips' in annotation:
            annotation['ips'].append(ipAddress)
        else:
            annotation['ips'] = [ipAddress]

    def setDefaultRoutes(self) -> None:
        for _, annotation in self.__annotations.items():
            annotation['default-route'] = []
            for ip in annotation['ips']:
                annotation['default-route'].append('.'.join(ip.split('/')[0].split('.')[:-1]) + '.254')

    def setNetworkAttachmentDefinitionNames(self, asn: str) -> None:
        for _, annotation in self.__annotations.items():
            interface = annotation['interface']
            if isExchange(interface):
                annotation['name'] = 'net-ix-{}'.format(getCompatibleName(interface))
            elif isServiceNetwork(interface):
                annotation['name'] = getCompatibleName(interface)
            else:
                annotation['name'] = 'net-{}-{}'.format(asn, getCompatibleName(interface))

    def getAnnotations(self) -> str:
        return json.dumps(list(self.__annotations.values()), separators=(',', ':'))

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

    def parseServices(self) -> None:
        for service_name in self.__docker_compose_file['services']:
            if service_name != BaseImageName:
                service = self.__docker_compose_file['services'][service_name]
                template = ServiceTemplate()
                template.setObjectName(getCompatibleName(service_name))
                template.setNamespace(self.__namespace)
                template.setImageName('{}-{}'.format(self.__project_name, service_name))
                template.setContainerName(getCompatibleName(service['container_name']))
                
                role = ''
                network_annotations = NetworkAnnotations()
                for label in service['labels']:
                    label_value = service['labels'][label]
                    if isNetworkLabel(label):
                        network_name = getNetworkNameFromLabel(label)
                        if isNetworkInterfaceLabel(label):
                            network_annotations.addNetworkAnnotation(network_name, label_value, self.__namespace)
                        elif isNetworkAddressLabel(label):
                            network_annotations.addIpAddress(network_name, label_value)
                            mask = label_value.split('/')[1]
                            label_value = label_value.split('/')[0]
                            template.setNetworkMaskLabel(network_name, mask)
                    elif isRoleLabel(label):
                        label_value = getCompatibleName(label_value)
                        role = label_value
                    elif isClassLabel(label):
                        label_value = getAlphaNumeric(label_value)
                    template.addLabel(label, label_value)

                network_annotations.setNetworkAttachmentDefinitionNames(service['labels'][AsnLabel])
                if role not in ['Router', 'Router']:
                    network_annotations.setDefaultRoutes()
                template.setNetworkAnnotations(network_annotations.getAnnotations())
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
