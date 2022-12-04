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

KubernetesCompilerFileTemplates['host'] = """\
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

class Kubernetes(object):

    __docker_files_path: str
    __docker_compose_file: str
    __namespace: str
    __interface: str
    __files: Dict[str, str]
    __project_name: str

    def __init__(self, dockerFilesPath: str = 'output', namespace: str = 'seed', interface: str = 'eth0') -> None:
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

    def getKubernetesName(self, name: str) -> str:
        return name.replace('_', '-').replace('.','-').replace(' ', '-')

    def getYamlFileName(self, name: str) -> str:
        return self.getKubernetesName(name) + '.yml'

    def getAlphaNumeric(self, string: str) -> str:
        return re.sub(r'\W+', '', string)

    def parseNetworks(self) -> None:
        for network in self.__docker_compose_file['networks']:
            self.__files[self.getYamlFileName(network)] = KubernetesCompilerFileTemplates['network'].format(
                networkName = self.getKubernetesName(network), 
                namespace = self.__namespace, 
                interface = self.__interface)

    def getNetworkAnnotations(self, networks: Dict[str, List[str]], namespace: str, asn: str, isRouter: bool = False) -> str:
        annotations = []
        for _, network in networks.items():
            net = {}
            net['namespace'] = namespace
            net['interface'] = network[0]
            if network[0].startswith('ix'):
                net['name'] = 'net-ix-{}'.format(network[0])
            else:
                net['name'] = 'net-{}-{}'.format(asn, network[0])
            net['ips'] = [network[1]]
            if not isRouter:
                net['default-route'] = ['.'.join(network[1].split('/')[0].split('.')[:-1]) + '.254']
            annotations.append(net)
        return json.dumps(annotations, separators=(',', ':'))

    def parseServices(self) -> None:
        for service_name in self.__docker_compose_file['services']:
            if service_name != 'cfee3a34e9c68ac1d16035a81a926786':
                service = self.__docker_compose_file['services'][service_name]
                template = yaml.load(KubernetesCompilerFileTemplates['host'], Loader=yaml.FullLoader)
                template['metadata']['name'] = self.getKubernetesName(service_name)
                template['metadata']['namespace'] = self.__namespace
                template['spec']['containers'][0]['image'] = '{}-{}'.format(self.__project_name, service_name)
                template['spec']['containers'][0]['name'] = self.getKubernetesName(service['container_name'])
                
                networks = {}
                role = ''
                is_router = False
                for label in service['labels']:
                    label_value = service['labels'][label]
                    if label.startswith('org.seedsecuritylabs.seedemu.meta.net'):
                        network_number = label.split('.')[5]
                        field = label.split('.')[6]
                        if field == 'name':
                            networks[network_number] = [label_value, None]
                        elif field == 'address':
                            networks[network_number][1] = label_value
                            label_value = label_value.split('/')[0]
                            template['metadata']['labels']['org.seedsecuritylabs.seedemu.meta.net.{}.mask'.format(network_number)] = '24'
                    elif label == 'org.seedsecuritylabs.seedemu.meta.role':
                        label_value = self.getKubernetesName(label_value)
                        if label_value.startswith('Route'):
                            is_router = True
                    elif label.startswith('org.seedsecuritylabs.seedemu.meta.class'):
                        label_value = self.getAlphaNumeric(label_value)
                    template['metadata']['labels'][label] = label_value

                template['metadata']['annotations']['k8s.v1.cni.cncf.io/networks'] = self.getNetworkAnnotations(networks, self.__namespace, 
                    service['labels']['org.seedsecuritylabs.seedemu.meta.asn'], is_router)
                self.__files[self.getYamlFileName(service_name)] = yaml.dump(template, sort_keys=False)

    def compile(self) -> None:
        self.parseNetworks()
        self.parseServices()
        output_directory = os.path.join(self.__docker_files_path, 'k8s')
        template_directory = os.path.join(output_directory, 'templates')
        os.makedirs(template_directory, exist_ok = True)
        for filename, data in self.__files.items():
            with open(os.path.join(template_directory, filename), 'w') as file:
                file.write(data)


if __name__ == "__main__":
    obj = Kubernetes('/Users/rajeevrmenon/work/cuboulder/fall_2022/csci_7000_005/project/seed-pods/examples/B00-mini-internet/output', interface='enp4s0f0np0')
    obj.compile()


