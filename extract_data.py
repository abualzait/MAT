import os
import re

base_dir = r"C:\Users\Abual\AntiGravity Workspace\Amman Police Stations"
html_path = os.path.join(base_dir, "Police_Station_Finder.html")
data_dir = os.path.join(base_dir, "data")
json_path = os.path.join(data_dir, "amman_areas.json")

os.makedirs(data_dir, exist_ok=True)

with open(html_path, "r", encoding="utf-8") as f:
    content = f.read()

print("Original HTML length:", len(content))

# Look for the start of the array
match = re.search(r'const ammanAreas = (\[.*?\]);', content, flags=re.DOTALL)
if match:
    json_data = match.group(1)
    
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(json_data)
        
    print(f"Extracted JSON array of length {len(json_data)} to {json_path}")
    
    replacement = """let ammanAreas = [];
        // Data is now fetched dynamically from the server to reduce file size
        fetch('/api/v1/mat/areas')
            .then(res => res.json())
            .then(data => {
                ammanAreas = data;
                console.log("Loaded " + ammanAreas.length + " areas dynamically.");
            })
            .catch(err => {
                console.error("Failed to load map data", err);
                const errorMsg = document.getElementById('errorMsg');
                if (errorMsg) {
                    errorMsg.textContent = "فشل تحميل بيانات المناطق. تأكد من الاتصال بالخادم.";
                    errorMsg.classList.add('active');
                }
            });"""
            
    new_content = content[:match.start()] + replacement + content[match.end():]
    
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(new_content)
        
    print("New HTML length:", len(new_content))
    print("Successfully decoupled data.")
else:
    print("Could not find ammanAreas array using regex.")
