
import psutil
import time

print("CLOUDOPS MONITORING STARTED")

while True:
    cpu = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory().percent
    disk = psutil.disk_usage("C:\\").percent

    print("--------------------------")
    print("CPU Usage:", cpu, "%")
    print("RAM Usage:", ram, "%")
    print("Disk Usage:", disk, "%")

    time.sleep(2)
