// map.js - Unified map logic for Nexus Dashboard

document.addEventListener('DOMContentLoaded', () => {
    // We wait for the 'stations' tab to become active before fully rendering the map
    // to avoid Leaflet rendering bugs in hidden divs.
});

let unifiedMap = null;
let policeStationsData = [];

// Override switchTab from app.js to initialize map when the stations tab is opened
const originalSwitchTab = window.switchTab;
window.switchTab = function(tabId) {
    if (originalSwitchTab) {
        originalSwitchTab(tabId);
    }
    if (tabId === 'stations') {
        if (!unifiedMap) {
            initUnifiedMap();
        } else {
            unifiedMap.invalidateSize();
        }
    }
};

async function initUnifiedMap() {
    const loader = document.getElementById('unifiedMapLoader');
    if (loader) loader.style.display = 'none';

    // Default to Amman center
    unifiedMap = L.map('map').setView([31.95, 35.92], 12);

    // Use local offline tiles
    L.tileLayer('/tiles/{z}/{x}/{y}.png', {
        minZoom: 10,
        maxZoom: 16,
        attribution: 'Amman Nexus Local Map',
        errorTileUrl: '/tiles/offline_tile.svg'
    }).addTo(unifiedMap);

    // Fetch areas and stations
    try {
        const res = await fetch('/api/areas');
        if (res.ok) {
            const data = await res.json();
            // Data contains areas. The original logic matched areas to stations.
            // For the dashboard, we will just plot some key stations for now,
            // or extract stations if the data structure has them.
            plotDataOnMap(data);
        }
    } catch (e) {
        console.error("Failed to load map data", e);
    }
}

function plotDataOnMap(areas) {
    // Assuming areas is a list of objects with lat, lon, and name
    // This is a simplified representation of the original logic
    const bounds = L.latLngBounds();
    let count = 0;
    
    // Original data had police stations mapped, we'll plot a few to prove integration
    areas.slice(0, 100).forEach(area => {
        if (area.lat && area.lon) {
            L.circleMarker([area.lat, area.lon], {
                radius: 4,
                fillColor: "#E53E3E",
                color: "#1A365D",
                weight: 1,
                opacity: 1,
                fillOpacity: 0.8
            }).addTo(unifiedMap).bindPopup(`<b>${area.name || 'منطقة'}</b>`);
            bounds.extend([area.lat, area.lon]);
            count++;
        }
    });

    if (count > 0) {
        unifiedMap.fitBounds(bounds, { padding: [50, 50] });
    }
}
