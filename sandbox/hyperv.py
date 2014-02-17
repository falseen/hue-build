# Used code from openstack-nova nova/virt/hyperv.py and openstack-quantum
import logging
import uuid

import wmi

SERVER = "WIN-TEST-1"

INSTANCE = {
    "name": "Hortonworks Sandbox 2.0",
    "memory_mb": 2048,
    "vcpus": 2,
    "vhdfile": "C:\sandbox.vhd",
    "int_network": "Sandbox Network",
}

LOG = logging.getLogger('hyperv')


class Instance(object):
    def _find_internal_network(self, int_network):
        switch = self.conn.Msvm_VirtualSwitch(ElementName=int_network)
        if not switch:
            LOG.error("Network switch '%s' not found", int_network)
        return switch[0]

    def __init__(self, hyperv, name, vhdfile=None, memory_mb=1024, vcpus=1, int_network=None):
        self.hyperv = hyperv
        self.conn = self.hyperv.conn
        self.name = name
        self._create(name)

        self.set_memory(memory_mb)
        self.set_cpus(vcpus)

        if vhdfile:
            self.add_vhd(vhdfile)

        if int_network:
            self.create_nic(int_network)

    def _create(self, name):
        data = self.conn.Msvm_VirtualSystemGlobalSettingData.new()
        data.ElementName = name

        # create VM
        self.hyperv.management.DefineVirtualSystem([], None, data.GetText_(1))
        self.vm = self.conn.Msvm_ComputerSystem(ElementName=name)[0]

        # get settings
        self.vm_settings = self.vm.associators(
            wmi_result_class='Msvm_VirtualSystemSettingData')
        self.vm_setting = [s for s in self.vm_settings
                           if s.SettingType == 3][0] # avoid snapshots
        self.mem_setting = self.vm_setting.associators(
            wmi_result_class='Msvm_MemorySettingData')[0]
        self.cpu_settings = self.vm_setting.associators(
            wmi_result_class='Msvm_ProcessorSettingData')[0]
        self.rasds = self.vm_settings[0].associators(
            wmi_result_class='MSVM_ResourceAllocationSettingData')
        LOG.info('Created vm %s...', name)

    def _clone_wmi_obj(self, wmi_class, wmi_obj):
        """Clone a WMI object"""
        cl = self.conn.__getattr__(wmi_class) # get the class
        newinst = cl.new()
        #Copy the properties from the original.
        for prop in wmi_obj._properties:
            newinst.Properties_.Item(prop).Value = \
                wmi_obj.Properties_.Item(prop).Value
        return newinst

    def set_memory(self, memory_mb):
        mem = long(str(memory_mb))
        self.mem_setting.VirtualQuantity = mem
        self.mem_setting.Reservation = mem
        self.mem_setting.Limit = mem
        self.hyperv.management.ModifyVirtualSystemResources(self.vm.path_(), [self.mem_setting.GetText_(1)])
        LOG.info('Set memory [%s MB] for vm %s...', mem, self.name)

    def set_cpus(self, vcpus):
        vcpus = long(vcpus)
        self.cpu_settings.VirtualQuantity = vcpus
        self.cpu_settings.Reservation = vcpus
        self.cpu_settings.Limit = 100000 # static assignment to 100%
        self.hyperv.management.ModifyVirtualSystemResources(self.vm.path_(), [self.cpu_settings.GetText_(1)])
        LOG.info('Set vcpus [%s] for vm %s...', vcpus, self.name)

    def add_vhd(self, vhdfile):
        ide_controller = [r for r in self.rasds
                          if r.ResourceSubType == 'Microsoft Emulated IDE Controller' and r.Address == "0"][0]
        disk_default = self.conn.query(
            "SELECT * FROM Msvm_ResourceAllocationSettingData \
WHERE ResourceSubType LIKE 'Microsoft Synthetic Disk Drive'\
AND InstanceID LIKE '%Default%'")[0]
        disk_drive = self._clone_wmi_obj(
            'Msvm_ResourceAllocationSettingData', disk_default)
        disk_drive.Parent = ide_controller.path_()
        disk_drive.Address = 0
        _, new_resources, _ = self.hyperv.management.AddVirtualSystemResources([disk_drive.GetText_(1)],
                                                                               self.vm.path_())
        disk_drive_path = new_resources[0]
        LOG.info('New disk drive path is %s', disk_drive_path)
        #Find the default VHD disk object.
        vhd_default = self.conn.query(
            "SELECT * FROM Msvm_ResourceAllocationSettingData \
WHERE ResourceSubType LIKE 'Microsoft Virtual Hard Disk' AND \
InstanceID LIKE '%Default%' ")[0]
        #Clone the default and point it to the image file.
        vhd_disk = self._clone_wmi_obj(
            'Msvm_ResourceAllocationSettingData', vhd_default)
        vhd_disk.Parent = disk_drive_path
        vhd_disk.Connection = [vhdfile]
        self.hyperv.management.AddVirtualSystemResources([vhd_disk.GetText_(1)],
                                                         self.vm.path_())
        LOG.info('Created disk [%s] for vm %s...', vhdfile, self.name)

    def create_nic(self, int_network):
        switch = self._find_internal_network(int_network)
        emulatednics_data = self.conn.Msvm_EmulatedEthernetPortSettingData()
        default_nic_data = [n for n in emulatednics_data
                            if n.InstanceID.rfind('Default') > 0]
        new_nic_data = self._clone_wmi_obj(
            'Msvm_EmulatedEthernetPortSettingData',
            default_nic_data[0])
        new_port, ret_val = self.hyperv.switch_svc.CreateSwitchPort(Name=uuid.uuid1().hex,
                                                                    FriendlyName=self.name,
                                                                    ScopeOfResidence="",
                                                                    VirtualSwitch=switch.path_())
        if ret_val != 0:
            LOG.error('Failed creating a port on the vswitch (error %s)' % ret_val)
            raise Exception('Failed creating port for %s' % self.name)
        LOG.info("Created switch port %s on switch %s", self.name, switch.path_())
        new_nic_data.Connection = [new_port]
        self.hyperv.management.AddVirtualSystemResources([new_nic_data.GetText_(1)],
                                                         self.vm.path_())
        LOG.info("Created nic for %s ", self.name)


class HyperV(object):
    def __init__(self, server_name):
        connection = wmi.connect_server(server=server_name, namespace=r"root\virtualization")
        self.conn = wmi.WMI(wmi=connection)
        self.management = self.conn.Msvm_VirtualSystemManagementService()[0]
        self.switch_svc = self.conn.Msvm_VirtualSwitchManagementService()[0]

    def create(self, *args, **kwargs):
        return Instance(self, *args, **kwargs)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    hyperv = HyperV(SERVER)
    instance = hyperv.create(**INSTANCE)