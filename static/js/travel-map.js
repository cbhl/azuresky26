(function () {
  const container = document.getElementById("travel-map");
  const dataEl = document.getElementById("travel-map-data");
  if (!container || !dataEl || typeof L === "undefined") {
    return;
  }

  let mapData;
  try {
    mapData = JSON.parse(dataEl.textContent);
  } catch (_err) {
    return;
  }

  if (!mapData.routes?.length || !mapData.airports?.length) {
    return;
  }

  const prefersDark =
    window.matchMedia &&
    window.matchMedia("(prefers-color-scheme: dark)").matches;

  const map = L.map(container, {
    scrollWheelZoom: false,
    attributionControl: true,
  });

  L.tileLayer(
    prefersDark
      ? "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
      : "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
    {
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
      subdomains: "abcd",
      maxZoom: 19,
    }
  ).addTo(map);

  const routeStyle = {
    color: prefersDark ? "#5eb0ff" : "#0070e0",
    weight: 1.5,
    opacity: 0.55,
  };

  const bounds = L.latLngBounds([]);

  for (const route of mapData.routes) {
    const line = L.polyline(
      [
        [route.lat1, route.lon1],
        [route.lat2, route.lon2],
      ],
      routeStyle
    );
    line.addTo(map);
    bounds.extend([route.lat1, route.lon1]);
    bounds.extend([route.lat2, route.lon2]);
  }

  const markerStyle = {
    radius: 4,
    fillColor: prefersDark ? "#5eb0ff" : "#0070e0",
    color: prefersDark ? "#ffffff" : "#004080",
    weight: 1,
    opacity: 1,
    fillOpacity: 0.9,
  };

  for (const airport of mapData.airports) {
    const marker = L.circleMarker([airport.lat, airport.lon], markerStyle);
    const label = airport.city
      ? `${airport.code} (${airport.city})`
      : airport.code;
    marker.bindTooltip(label, { direction: "top", offset: [0, -4] });
    marker.addTo(map);
    bounds.extend([airport.lat, airport.lon]);
  }

  map.fitBounds(bounds, { padding: [24, 24] });
})();
