const compactQuery = `[out:json][timeout:25];area["ISO3166-1"="JO"]->.searchArea;(node["amenity"="police"](area.searchArea)(31.0,35.0,33.0,37.0);way["amenity"="police"](area.searchArea)(31.0,35.0,33.0,37.0);relation["amenity"="police"](area.searchArea)(31.0,35.0,33.0,37.0););out center;`;
console.log(compactQuery);
