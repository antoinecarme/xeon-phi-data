# This script is used to control fan speeds (and noise level) on an  Asrock 2U4N-F/X200 server node
# the nodes are 1U nodes which make a lot of noise when using default settings.
# Each node has 4 too small fans with max speed of 21000 RPM)

# We use IPMI services to set fan speed based of temmperatures coming from various sensors
# This script runs endlessly and sets the 4 fan speeds every 30 seconds based on maximum temperature reading.

# The sript is made the most verbose possible, each IPMI command sent to the system is displayed.

# usage (need root access) : sudo python fan_control.py

# This table has been filled manually based on the noise level observed when running some cpu-intensive tasks (pyaf benchmarks).
# interpretation : When the max temperature is between 35C and 45C, set the fan speed to 20% of max speed.

CPU_TEMPERATURE_FAN_SPEED_MAPPING = {35 : 18, 45 : 22 , 55 : 25, 60 : 30, 65 : 35 , 75 : 40, 80 : 45 , 90 : 50}

def set_fan_zone_level():
    return

def get_values(label, cmd):
    print("EXECUTING" , label, cmd)
    import subprocess
    ls = subprocess.call(cmd + " > /tmp/fan_control_command_output.txt", shell=True)
    output = []
    with open("/tmp/fan_control_command_output.txt") as f:
        output = f.readlines()[0][:-1]
    print("OUTPUT" , label, output)
    return output

def set_fan_speed(percentage_of_max):
    print("SET_FAN_SPEED_PERCENTAGE" , percentage_of_max)
    # values are from 0 to 64, 0 is smart Fan (bios control), 1 is the minimum speed, and 64 is full speed
    ipmi_value = int(64 * percentage_of_max / 100)
    # avoid too extermal values
    ipmi_value = max(12 , ipmi_value)
    ipmi_value = min(60 , ipmi_value)
    ipmi_value = str(ipmi_value)
    cmd = "/usr/sbin/ipmi-raw 00 3a 01 "
    cmd = cmd + " " + ipmi_value + " " + ipmi_value + " " + ipmi_value + " " + ipmi_value 
    cmd = cmd + " " + ipmi_value + " " + ipmi_value + " " + ipmi_value + " " + ipmi_value 
    l_exec_status = get_values("SET_FAN_SPEED", cmd) 
    print(l_exec_status)

def get_fan_speeds():
    l_fan_speed_cmd = "/usr/sbin/ipmi-sensors   | grep Fan | grep -v 'N/A'  | cut -f 4 -d '|' | xargs"
    l_fan_speeds = get_values("READ_FAN_SPEED", l_fan_speed_cmd).split(" ")
    l_fan_speeds = [float(x) for x in l_fan_speeds]
    print("READ_FAN_SPEED", l_fan_speeds)
    return l_fan_speeds

def get_temperatures():
    l_temperature_cmd = "/usr/sbin/ipmi-sensors   | grep Temperature | grep -v 'N/A'  | cut -f 4 -d '|' | xargs"
    l_temperatures = get_values("TEMPERATURE", l_temperature_cmd).split(" ")
    l_temperatures = [float(x) for x in l_temperatures]
    print("TEMPERATURE", l_temperatures)
    return l_temperatures

def check_server_name():
    l_prod_cmd = "cat /sys/class/dmi/id/board_vendor  /sys/class/dmi/id/product_name /sys/class/dmi/id/board_name | xargs"
    l_prod_name = get_values("CHECK_SERVER_MODEL", l_prod_cmd)
    return(l_prod_name)

def get_interpolated_percentage(max_temp):
    max_temp_boundary_high = min([x for x in CPU_TEMPERATURE_FAN_SPEED_MAPPING.keys() if max_temp <= x] + [90])
    max_temp_boundary_low = max([35] + [x for x in CPU_TEMPERATURE_FAN_SPEED_MAPPING.keys() if x <= max_temp ])
    percentage_of_max_high = CPU_TEMPERATURE_FAN_SPEED_MAPPING.get(max_temp_boundary_high)
    percentage_of_max_low = CPU_TEMPERATURE_FAN_SPEED_MAPPING.get(max_temp_boundary_low)
    percentage_of_max = percentage_of_max_high
    if(percentage_of_max_high > percentage_of_max_low):
        percentage_of_max = percentage_of_max_low + (max_temp - max_temp_boundary_low) / (max_temp_boundary_high - max_temp_boundary_low) * (percentage_of_max_high - percentage_of_max_low)
    print("INTERPOLATED_DATA" , (max_temp_boundary_low, max_temp_boundary_high, percentage_of_max_low, percentage_of_max_high), max_temp , percentage_of_max)
    return percentage_of_max

def run():
    server_name = check_server_name()
    if(server_name != "ASRockRack 2U4N-F/X200 X200D6HM"):
        print("THIS_SCRIPT_IS_ONLY_TO_BE_USED_ON_A" +  "2U4N-F/X200" + " SERVER !!!!!")
        return
    import time
    while(0 == 0):
        print("Start : %s" % time.ctime())
        get_fan_speeds()
        l_temps = get_temperatures()
        max_temp = max(l_temps)
        print("MAX_TEMP" , max_temp)
        percentage_of_max = get_interpolated_percentage(max_temp)
        set_fan_speed(percentage_of_max + 5)
        # wait for fans to stabilize !!!
        time.sleep( 1 )
        get_fan_speeds()
        lSeconds = 10
        print("SLEEPING_FOR" , lSeconds , "seconds.")
        time.sleep( lSeconds )


run()
