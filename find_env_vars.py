import re

with open('aurafoods_erp/settings.py', 'r') as f:
    content = f.read()

matches = re.findall(r"os\.environ\.get\([\"']([^\"']+)[\"']", content)
matches += re.findall(r"env_bool\([\"']([^\"']+)[\"']", content)
matches += re.findall(r"env_int\([\"']([^\"']+)[\"']", content)
matches += re.findall(r"env_str\([\"']([^\"']+)[\"']", content)

for m in sorted(set(matches)):
    print(m)