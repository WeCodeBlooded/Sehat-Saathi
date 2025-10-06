import React, { useState, useEffect, useRef, useMemo } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

export default function HospitalLocator({ backend, uid }) {
  // Search center (chosen place) coordinates
  const [searchLat, setSearchLat] = useState('');
  const [searchLng, setSearchLng] = useState('');
  // User's physical current location (for distance display)
  const [userLat, setUserLat] = useState('');
  const [userLng, setUserLng] = useState('');
  const [loading, setLoading] = useState(false);
  const [hospitals, setHospitals] = useState([]);
  const [error, setError] = useState('');
  const SPECIALTIES = useMemo(()=>['cardiology','dermatology','neurology','orthopedics','pediatrics','general','ent','ophthalmology','other'],[]);
  const [speciality, setSpeciality] = useState('');
  const [otherSpec, setOtherSpec] = useState('');
  const [placeQuery, setPlaceQuery] = useState('');
  const [suggestions, setSuggestions] = useState([]);
  const [fetchingSug, setFetchingSug] = useState(false);
  const sugAbort = useRef(null);
  const [loadingList, setLoadingList] = useState(false);
  const mapRef = useRef(null);
  const markersRef = useRef(null);
  const [geoDenied, setGeoDenied] = useState(false);

  useEffect(() => {
    if (!mapRef.current && searchLat && searchLng) {
      mapRef.current = L.map('mapViewport').setView([parseFloat(searchLat), parseFloat(searchLng)], 13);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; OpenStreetMap contributors' }).addTo(mapRef.current);
      markersRef.current = L.layerGroup().addTo(mapRef.current);
    }
    // Pan map if coords change
    if (mapRef.current && searchLat && searchLng) {
      mapRef.current.setView([parseFloat(searchLat), parseFloat(searchLng)], mapRef.current.getZoom() || 13);
    }
  }, [searchLat, searchLng]);

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
      const latv = pos.coords.latitude.toFixed(6);
      const lngv = pos.coords.longitude.toFixed(6);
      setUserLat(latv); setUserLng(lngv);
      // If no search center chosen yet, use current location
      if (!searchLat || !searchLng) { setSearchLat(latv); setSearchLng(lngv); }
      setGeoDenied(false);
    }, err => setError(err.message));
  };

  // Attempt automatic user location fetch on initial mount (non-blocking)
  useEffect(() => {
    if (!userLat && navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(pos => {
        const latv = pos.coords.latitude.toFixed(6);
        const lngv = pos.coords.longitude.toFixed(6);
        setUserLat(latv); setUserLng(lngv);
      }, () => setGeoDenied(true), { enableHighAccuracy: false, timeout: 5000 });
    }
  }, [userLat]);

  // Debounced place suggestions
  useEffect(() => {
    if (!placeQuery || placeQuery.trim().length < 2) { setSuggestions([]); return; }
    const handle = setTimeout(async () => {
      try {
        setFetchingSug(true);
        if (sugAbort.current) sugAbort.current.abort();
        sugAbort.current = new AbortController();
        const body = { query: placeQuery.trim(), limit: 8 };
  if (searchLat && searchLng) { body.bias_lat = parseFloat(searchLat); body.bias_lng = parseFloat(searchLng); }
        const res = await fetch(`${backend}/place_autocomplete`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body), signal: sugAbort.current.signal });
        const data = await res.json();
        if (res.ok) {
          setSuggestions(data.suggestions || []);
        } else {
          setSuggestions([]);
        }
      } catch (e) {
        if (e.name !== 'AbortError') setSuggestions([]);
      } finally { setFetchingSug(false); }
    }, 350);
    return () => clearTimeout(handle);
  }, [placeQuery, backend, searchLat, searchLng]);

  const pickSuggestion = (s) => {
    if (s.lat && s.lng) {
      setSearchLat(parseFloat(s.lat).toFixed(6));
      setSearchLng(parseFloat(s.lng).toFixed(6));
    }
    setPlaceQuery(s.formatted || s.name || '');
    setSuggestions([]);
  };

  const search = async (e) => {
    e && e.preventDefault();
    if (!searchLat || !searchLng) {
      setError('Select a location (type and choose from suggestions or use your location)');
      return;
    }
  setLoading(true); setLoadingList(true); setError('');
    try {
      const spec = speciality === 'other' ? (otherSpec.trim() || '') : speciality;
      const res = await fetch(`${backend}/get_nearby_hospitals`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ uid, lat: parseFloat(searchLat), lng: parseFloat(searchLng), speciality: spec }) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Search failed');
      setHospitals(data.hospitals || []);
    } catch (e) { setError(e.message); } finally { setLoading(false); setLoadingList(false); }
  };

  return (
    <div className="feature-card">
      <h2>Hospital Locator</h2>
      <form onSubmit={search} className="grid-form">
        <label style={{position:'relative'}}>Location / Area
          <input value={placeQuery} onChange={e=>setPlaceQuery(e.target.value)} placeholder="Type village, town or area" />
          {suggestions.length>0 && (
            <div className="dropdown" style={{position:'absolute',top:'100%',left:0,right:0,zIndex:20,background:'var(--bg-alt)',border:'1px solid var(--border)',borderRadius:'6px',boxShadow:'var(--shadow)',maxHeight:200,overflow:'auto'}}>
              {suggestions.map(s => (
                <button type="button" key={s.id} className="dropdown-item" onClick={()=>pickSuggestion(s)} style={{display:'block',width:'100%',textAlign:'left',padding:'6px 8px',fontSize:'.65rem'}}>
                  <strong>{s.name}</strong><br/><span style={{opacity:.7}}>{s.formatted}</span>
                </button>
              ))}
              {fetchingSug && <div style={{padding:6,fontSize:'.6rem',opacity:.6}}>Loading…</div>}
            </div>
          )}
        </label>
        <label>Speciality
          <select value={speciality} onChange={e=>setSpeciality(e.target.value)}>
            <option value="">-- Any --</option>
            {SPECIALTIES.map(s => <option key={s} value={s}>{s === 'other' ? 'Other...' : s.charAt(0).toUpperCase()+s.slice(1)}</option>)}
          </select>
          {speciality === 'other' && (
            <input style={{marginTop:4}} value={otherSpec} onChange={e=>setOtherSpec(e.target.value)} placeholder="Enter speciality" />
          )}
        </label>
        <div className="row-span-full btn-row">
          <button type="button" onClick={detectLocation} className="secondary">{userLat? 'Refresh My Location' : 'Use My Location'}</button>
          <button className="primary" disabled={!searchLat || !searchLng || loading}>{loading? 'Searching...':'Search'}</button>
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
            {(() => {
              if (userLat && userLng && h.latitude && h.longitude) {
                const R = 6371; // km
                const toRad = deg => deg * Math.PI/180;
                const hLat = parseFloat(h.latitude);
                const hLng = parseFloat(h.longitude);
                const uLat = parseFloat(userLat);
                const uLng = parseFloat(userLng);
                const dLat = toRad(hLat - uLat);
                const dLng = toRad(hLng - uLng);
                const a = Math.sin(dLat/2)**2 + Math.cos(toRad(uLat)) * Math.cos(toRad(hLat)) * Math.sin(dLng/2)**2;
                const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
                const dist = R * c;
                return <p><strong>{dist.toFixed(2)} km</strong> from your current location</p>;
              } else if (h.distance_km != null) {
                return <p><strong>{h.distance_km.toFixed(2)} km</strong> from search center</p>;
              }
              return null;
            })()}
            {h.specialties && <p className="tags">{h.specialties.slice(0,6).map(s=> <span key={s}>{s}</span>)}</p>}
            {h.latitude && h.longitude && (
              <a className="map-link" href={`https://www.google.com/maps?q=${h.latitude},${h.longitude}`} target="_blank" rel="noreferrer">Open in Maps ↗</a>
            )}
          </div>
        ))}
      </div>
      <p className="hint" style={{marginTop:8,fontSize:'.6rem'}}>
        Distances use your current location{userLat? ` (lat ${userLat}, lng ${userLng})` : geoDenied ? ' (permission denied – showing search center distances)' : ' (fetching...)'}.
        {geoDenied && ' Click "Use My Location" to retry.'}
      </p>
    </div>
  );
}
