import re
import yaml
import json
import os.path
import ipaddress
from typing import Dict

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
      "type": "vxlan",
      "dev": "{interface}",
      "vni": {vni},
      "group": "{group}",
      "dstPort": 4789,
      "cidr": "{cidr}"
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

KubernetesCompilerFileTemplates['helmchart'] = """\
name: {name}
description: SEED-generated helm chart for internet emulation
version: 0.0.1
apiVersion: v1
"""

BaseImageName = "cfee3a34e9c68ac1d16035a81a926786"
NetworkLabelPrefix = "org.seedsecuritylabs.seedemu.meta.net"
NetworkMaskLabelTemplate = "org.seedsecuritylabs.seedemu.meta.net.{}.mask"
RoleLabel = "org.seedsecuritylabs.seedemu.meta.role"
ClassLabel = "org.seedsecuritylabs.seedemu.meta.class"
AsnLabel = "org.seedsecuritylabs.seedemu.meta.asn"

NetworkMapping: Dict[str, str] = {} 

def getCompatibleName(name: str) -> str:
    return name.replace('_', '-').replace('.', '-').replace(' ', '-')


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


def getNetworkNumberFromLabel(label: str) -> str:
    return label.split('.')[5]


def isNetworkAddressLabel(label: str) -> bool:
    return isNetworkLabel(label) and label.split('.')[6] == "address"


def isNetworkNameLabel(label: str) -> bool:
    return isNetworkLabel(label) and label.split('.')[6] == "name"


def isExchange(networkName: str) -> bool:
    return networkName.startswith('ix')


def isServiceNetwork(networkName: str) -> bool:
    return networkName == "000_svc"

def getShortNetworkName(networkName: str) -> str:
    if networkName not in NetworkMapping:
        NetworkMapping[networkName] = 'net' + str(len(NetworkMapping))
    return NetworkMapping[networkName]


class ServiceTemplate(object):
    __template: str

    def __init__(self) -> None:
        self.__template = yaml.load(
            KubernetesCompilerFileTemplates['service'], Loader=yaml.FullLoader)

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

    def setNetworkMaskLabel(self, networkNumber: str, networkMask: str) -> None:
        self.__template['metadata']['labels'][NetworkMaskLabelTemplate.format(
            networkNumber)] = networkMask

    def setNetworkAnnotations(self, networkAnnotations: str) -> None:
        self.__template['metadata']['annotations']['k8s.v1.cni.cncf.io/networks'] = networkAnnotations

    def getYamlFile(self) -> str:
        return yaml.dump(self.__template, sort_keys=False)


class NetworkAnnotations(object):
    __annotations: Dict[str, Dict[str, str]]

    def __init__(self) -> None:
        self.__annotations = {}

    def addNetworkAnnotation(self, networkNumber: str, networkName: str, namespace: str) -> None:
        annotation = {}
        annotation['interface'] = networkName
        annotation['namespace'] = namespace
        self.__annotations[networkNumber] = annotation

    def addIpAddress(self, networkNumber: str, ipAddress: str) -> None:
        annotation = self.__annotations[networkNumber]
        if 'ips' in annotation:
            annotation['ips'].append(ipAddress)
        else:
            annotation['ips'] = [ipAddress]

    def setDefaultRoutes(self) -> None:
        for _, annotation in self.__annotations.items():
            annotation['default-route'] = []
            for ip in annotation['ips']:
                annotation['default-route'].append(
                    '.'.join(ip.split('/')[0].split('.')[:-1]) + '.254')

    def setNetworkNames(self, asn: str) -> None:
        for _, annotation in self.__annotations.items():
            interface = annotation['interface']
            if isExchange(interface):
                annotation['name'] = getShortNetworkName('net-ix-{}'.format(
                    getCompatibleName(interface)))
            elif isServiceNetwork(interface):
                annotation['name'] = getShortNetworkName(getCompatibleName(interface))
            else:
                annotation['name'] = getShortNetworkName('net-{}-{}'.format(
                    asn, getCompatibleName(interface)))

    def getAnnotations(self) -> str:
        return json.dumps(list(self.__annotations.values()), separators=(',', ':'))


class Kubernetes(object):

    __docker_files_path: str
    __docker_compose_file: str
    __namespace: str
    __interface: str
    __files: Dict[str, str]
    __project_name: str
    __vxlan_group: ipaddress.ip_address
    __vni: int

    def __init__(self, dockerFilesPath: str = './output', namespace: str = 'seed', interface: str = 'eth0') -> None:
        self.__docker_files_path = dockerFilesPath
        self.__namespace = namespace
        self.__interface = interface
        self.__files = {}
        self.__project_name = os.path.basename(dockerFilesPath)
        self.__vxlan_group = ipaddress.ip_address("239.1.1.1")
        self.__vni = 100
        try:
            with open(os.path.join(self.__docker_files_path, 'docker-compose.yml'), 'r') as file:
                self.__docker_compose_file = yaml.load(
                    file, Loader=yaml.FullLoader)
        except Exception as e:
            raise Exception('Error opening the docker compose file: {}')

    def parseNetworks(self) -> None:
        for network in self.__docker_compose_file['networks']:
            self.__files[getYamlFileName(network)] = KubernetesCompilerFileTemplates['network'].format(
                networkName=getShortNetworkName(getCompatibleName(network)),
                namespace=self.__namespace,
                interface=self.__interface,
                vni=self.__vni,
                group=str(self.__vxlan_group),
                cidr=self.__docker_compose_file['networks'][network]['ipam']['config'][0]['subnet']
                )
            self.__vxlan_group += 1
            self.__vni += 1

    def parseServices(self) -> None:
        for service_name in self.__docker_compose_file['services']:
            if service_name == BaseImageName:
                continue
            service = self.__docker_compose_file['services'][service_name]
            template = ServiceTemplate()
            template.setObjectName(getCompatibleName(service_name))
            template.setNamespace(self.__namespace)
            template.setImageName(
                '{}-{}'.format(self.__project_name, service_name))
            template.setContainerName(
                getCompatibleName(service['container_name']))

            role = ''
            network_annotations = NetworkAnnotations()
            for label in service['labels']:
                label_value = service['labels'][label]
                if isNetworkLabel(label):
                    network_number = getNetworkNumberFromLabel(label)
                    if isNetworkNameLabel(label):
                        network_annotations.addNetworkAnnotation(
                            network_number, label_value, self.__namespace)
                    elif isNetworkAddressLabel(label):
                        network_annotations.addIpAddress(
                            network_number, label_value)
                        mask = label_value.split('/')[1]
                        label_value = label_value.split('/')[0]
                        template.setNetworkMaskLabel(network_number, mask)
                elif isRoleLabel(label):
                    label_value = getCompatibleName(label_value)
                    role = label_value
                elif isClassLabel(label):
                    label_value = getAlphaNumeric(label_value)
                template.addLabel(label, label_value)

            network_annotations.setNetworkNames(
                service['labels'][AsnLabel])
            if role not in ['Router', 'Route-Server']:
                network_annotations.setDefaultRoutes()
            template.setNetworkAnnotations(
                network_annotations.getAnnotations())
            self.__files[getYamlFileName(
                service_name)] = template.getYamlFile()

    def compile(self) -> None:
        self.parseNetworks()
        self.parseServices()
        output_directory = os.path.join(self.__docker_files_path, 'k8s')
        template_directory = os.path.join(output_directory, 'templates')
        os.makedirs(template_directory, exist_ok=True)
        for filename, data in self.__files.items():
            with open(os.path.join(template_directory, filename), 'w') as file:
                file.write(data)
        with open(os.path.join(output_directory, 'Chart.yaml'), 'w') as file:
            file.write(KubernetesCompilerFileTemplates['helmchart'].format(
                name=self.__project_name))
