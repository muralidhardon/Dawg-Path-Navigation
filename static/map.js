// map.js - loads Google Maps and plots route stops + polyline
(function(){
  let map;
  let markers = [];
  let polyline;

  function loadGoogleMapsAndInit(callback) {
    // If already loaded
    if (window.google && window.google.maps) {
      return callback();
    }
    const key = window.GOOGLE_MAPS_API_KEY || '';
    if (!key) {
      alert('Google Maps API key not configured on backend (GOOGLE_MAPS_API_KEY)');
      return;
    }
    const s = document.createElement('script');
    s.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}`;
    s.defer = true;
    s.onload = callback;
    s.onerror = function(){ alert('Failed to load Google Maps script'); };
    document.head.appendChild(s);
  }

  function clearMap() {
    markers.forEach(m => m.setMap(null));
    markers = [];
    if (polyline) { polyline.setMap(null); polyline = null; }
  }

  function fitMapToMarkers() {
    if (!markers.length) return;
    const bounds = new google.maps.LatLngBounds();
    markers.forEach(m => bounds.extend(m.getPosition()));
    map.fitBounds(bounds);
  }

  async function fetchRouteStops(routeId) {
    const url = `/routes/${encodeURIComponent(routeId)}/stops`;
    const r = await fetch(url);
    if (!r.ok) throw new Error('Failed to fetch route stops');
    return r.json();
  }

  window.loadRouteOnMap = async function(routeId) {
    try {
      await new Promise((res,rej)=> loadGoogleMapsAndInit(res));
      if (!map) {
        map = new google.maps.Map(document.getElementById('map'), { zoom: 13, center: { lat: 47.6062, lng: -122.3321 } });
      }
      clearMap();
      const stops = await fetchRouteStops(routeId);
      if (!Array.isArray(stops) || !stops.length) {
        alert('No stops found for route ' + routeId);
        return;
      }
      const path = [];
      for (const s of stops) {
        const pos = { lat: parseFloat(s.lat), lng: parseFloat(s.lng) };
        path.push(pos);
        const marker = new google.maps.Marker({ position: pos, map, title: s.name });
        markers.push(marker);
      }
      polyline = new google.maps.Polyline({ path, geodesic: true, strokeColor: '#FF0000', strokeOpacity: 0.8, strokeWeight: 4 });
      polyline.setMap(map);
      fitMapToMarkers();
    } catch (err) {
      console.error(err);
      alert('Error loading route: ' + err.message);
    }
  }
})();
