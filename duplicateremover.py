import re

filetoread = "helloworld"
outputcode = []
x_current = 0
y_current = 0
e_current = 0
index_current = 0
index_prev = 0

class filereader:
    sourcefile = str(filetoread) + ".gcode" # Specify source file here
    totalgcode = ""

    with open(sourcefile,'r+') as r:  # Read lines from source file
        totalgcode = r.readlines()  # Total gcode is a list of lines

def filewriter(data, filename):
    targetfile = str(filename)+".gcode" # #Specify target file
    with open(targetfile,'w') as w:
        for i in data:
            w.write(i)

def getValue(line, key, default = None):
    if not key in line or (';' in line and line.find(key) > line.find(';')):
            return default
    subPart = line[line.find(key) + 1:]
    m = re.search('^[0-9]+\.?[0-9]*|^-[0-9]+\.?[0-9]*', subPart)
    if m == None:
            return default
    try:
            return round(float(m.group(0)),5)
    except:
            return default


filereader()
totalgcode = filereader.totalgcode

for line in totalgcode:
    if line.find("G1") != -1:
        index_prev = index_current
        x_prev = x_current
        y_prev = y_current
        e_prev = e_current

        index_current = totalgcode.index(line)
        x_current = getValue(line, 'X', -1)
        y_current = getValue(line, 'Y', -1)
        e_current = getValue(line, 'E', -1)

        if abs(index_current-index_prev) == 1:
            if x_current == x_prev and y_current == y_prev:
                if e_current > e_prev:
                    line = re.sub("G1", ";G1", line)
                if e_current < e_prev:
                    prevline = outputcode[index_current-1]
                    prevline = re.sub("G1", ";G1", prevline)
                    outputcode[index_current-1] = prevline
    outputcode.append(line)


filewriter(outputcode,str(filetoread) + "_patch")