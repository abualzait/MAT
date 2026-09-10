const compactQuery = `[out:json][timeout:25];area["name:en"="Amman Governorate"]->.searchArea;(node["amenity"="police"](area.searchArea);way["amenity"="police"](area.searchArea);relation["amenity"="police"](area.searchArea););out center;`;
console.log(compactQuery);

