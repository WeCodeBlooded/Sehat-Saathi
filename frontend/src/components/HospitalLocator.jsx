import React, { useState, useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

export default function HospitalLocator({ backend, uid }) {
  const [lat, setLat] = useState('');
  const [lng, setLng] = useState('');
  const [loading, setLoading] = useState(false);
  const [hospitals, setHospitals] = useState([]);
  const [error, setError] = useState('');
  const [speciality, setSpeciality] = useState('');
  const [loadingList, setLoadingList] = useState(false);
  const mapRef = useRef(null);
  const markersRef = useRef(null);

  useEffect(() => {
    if (!mapRef.current && lat && lng) {
      mapRef.current = L.map('mapViewport').setView([parseFloat(lat), parseFloat(lng)], 13);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; OpenStreetMap contributors' }).addTo(mapRef.current);
      markersRef.current = L.layerGroup().addTo(mapRef.current);
    }
    // Pan map if coords change
    if (mapRef.current && lat && lng) {
      mapRef.current.setView([parseFloat(lat), parseFloat(lng)], mapRef.current.getZoom() || 13);
    }
  }, [lat, lng]);

  useEffect(() => {
    if (markersRef.current) {
      markersRef.current.clearLayers();
      hospitals.forEach(h => {
        if (h.latitude && h.longitude) {
          const marker = L.marker([h.latitude, h.longitude]);
          marker.bindPopup(`<strong>${h.name}</strong><br/>${h.type||''}${h.distance_km!=null? `<br/>${h.distance_km.toFixed(2)} km`:''}`);
          marker.addTo(markersRef.current);
        }
      });
    }
  }, [hospitals]);

  const detectLocation = () => {
    if (!navigator.geolocation) return setError('Geolocation not supported');
    navigator.geolocation.getCurrentPosition(pos => {
      setLat(pos.coords.latitude.toFixed(6));
      setLng(pos.coords.longitude.toFixed(6));
    }, err => setError(err.message));
  };

  const search = async (e) => {
    e && e.preventDefault();
    if (!lat || !lng) return;
  setLoading(true); setLoadingList(true); setError('');
    try {
      const res = await fetch(`${backend}/get_nearby_hospitals`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ uid, lat: parseFloat(lat), lng: parseFloat(lng), speciality }) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Search failed');
      setHospitals(data.hospitals || []);
    } catch (e) { setError(e.message); } finally { setLoading(false); setLoadingList(false); }
  };

  return (
    <div className="feature-card">
      <h2>Hospital Locator</h2>
      <form onSubmit={search} className="grid-form">
        <label>Latitude<input value={lat} onChange={e=>setLat(e.target.value)} placeholder="e.g. 28.6139" /></label>
        <label>Longitude<input value={lng} onChange={e=>setLng(e.target.value)} placeholder="e.g. 77.2090" /></label>
        <label>Speciality<input value={speciality} onChange={e=>setSpeciality(e.target.value)} placeholder="cardio, ortho..." /></label>
        <div className="row-span-full btn-row">
          <button type="button" onClick={detectLocation} className="secondary">Use My Location</button>
          <button className="primary" disabled={!lat || !lng || loading}>{loading? 'Searching...':'Search'}</button>
        </div>
      </form>
      {error && <div className="alert error">{error}</div>}
      <div id="mapViewport" style={{height:'300px',border:'1px solid var(--border)',borderRadius:'var(--radius-m)',marginTop:'8px'}} />
      <div className="hospital-results">
        {loadingList && <div className="skeleton-grid">{Array.from({length:4}).map((_,i)=><div key={i} className="skeleton card" />)}</div>}
        {!loadingList && hospitals.length === 0 && <div className="empty">No hospitals yet. Search to see results.</div>}
        {hospitals.map(h => (
          <div key={`${h.name}-${h.latitude}-${h.longitude}`} className={`hospital-card ${h.is_recommended? 'recommended':''}`}>
            <div className="hc-header">
              <h4>{h.name}</h4>
              {h.is_recommended && <span className="badge">Recommended</span>}
            </div>
            <p className="muted">{h.type || 'facility'}</p>
            {h.distance_km != null && <p><strong>{h.distance_km.toFixed(2)} km</strong> away</p>}
            {h.specialties && <p className="tags">{h.specialties.slice(0,6).map(s=> <span key={s}>{s}</span>)}</p>}
            {h.latitude && h.longitude && (
              <a className="map-link" href={`https://www.google.com/maps?q=${h.latitude},${h.longitude}`} target="_blank" rel="noreferrer">Open in Maps ↗</a>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
