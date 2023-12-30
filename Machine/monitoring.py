from xml.dom.minidom import parseString


class MachineStateMonitor:

    def __init__(self, machine_name, devices_xml):

        self.machine_name = machine_name
        self.machine_availability = False
        self.selected_device = None
        # Machine Params
        self.devices_xml = devices_xml
        self.machine_params = {}

    def get_set_machine_availability(self, response):

        # Get the availability
        document = parseString(response.text)

        # Get all availabilities
        availabilities = document.getElementsByTagName('Availability')
        for availability in availabilities:
            if availability.getAttribute("dataItemId") == self.machine_name + "_avail_01":
                # Check status
                if availability.childNodes[0].nodeValue == "AVAILABLE":
                    self.machine_availability = True
                    return

        self.machine_availability = False

    def get_set_machine_type(self, response):

        # Get all Devices
        document = parseString(response.text)

        # Select the right machine
        devices = document.getElementsByTagName('DeviceStream')
        for device in devices:
            if device.getAttribute("name") == self.machine_name:
                self.selected_device = device
            return

    def update_machine_state(self, response):

        # Get all Devices
        document = parseString(response.text)

        # Start by updating machine availability
        self.get_set_machine_availability(response)

        if self.machine_availability:
            self.get_set_machine_type(response)
        else:
            return

        # Go through all component and assign values
        for component in self.selected_device.getElementsByTagName('ComponentStream'):

            # Get the component name
            component_name = component.getAttribute("name")
            if component_name not in self.machine_params:
                self.machine_params[component_name] = {}

            # Go through the child nodes of component stream
            for child_node in component.childNodes:
                if child_node.nodeName not in self.machine_params[component_name]:
                    self.machine_params[component_name][child_node.nodeName] = {}

                # Get the respective values
                for child_child_node in child_node.childNodes:
                    if child_child_node not in self.machine_params[component_name][child_node.nodeName]:
                        self.machine_params[component_name][child_node.nodeName][child_child_node.nodeName] = []

                    if child_child_node.firstChild is not None:
                        value = child_child_node.firstChild.nodeValue
                    else:
                        value = None
                    self.machine_params[component_name][child_node.nodeName][child_child_node.nodeName].append((child_child_node.getAttribute("name"), value))

        return True

