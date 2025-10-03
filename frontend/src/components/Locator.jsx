import React, { useState, useEffect } from 'react';
import './Locator.css';

// IMPORTANT: Make sure this URL matches your backend's address
const API_URL = 'https://1d897642e66b.ngrok-free.app';

export default function Locator({ onSelectHospital }) {
  const [hospitals, setHospitals] = useState([]);
  const [userLocation, setUserLocation] = useState(null);
  const [status, setStatus] = useState('pending'); // 'pending', 'loading', 'success', 'error'
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [favorites, setFavorites] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('fav_hospitals') || '[]');
    } catch (e) {
      return [];
    }
  });

  // This function calls the backend to get hospitals
  const fetchHospitals = async (latitude, longitude) => {
    // remember the user's location for distance calculations
    setUserLocation({ lat: latitude, lng: longitude });
    setStatus('loading');
    const uid = localStorage.getItem('user_uid');
    if (!uid) {
      setError("User not found. Please log in again.");
      setStatus('error');
      return;
    }

    try {
      const response = await fetch(`${API_URL}/get_nearby_hospitals`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ uid, lat: latitude, lng: longitude }),
      });
      const data = await response.json();
      if (response.ok) {
        setHospitals(data.hospitals || []);
        setStatus('success');
      } else {
        throw new Error(data.message || 'Failed to fetch hospitals');
      }
    } catch (err) {
      setError(err.message);
      setStatus('error');
    }
  };

  // Utility: haversine distance in km
  const haversineDistance = (lat1, lon1, lat2, lon2) => {
    const toRad = (v) => (v * Math.PI) / 180;
    const R = 6371; // km
    const dLat = toRad(lat2 - lat1);
    const dLon = toRad(lon2 - lon1);
    const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) *
      Math.sin(dLon / 2) * Math.sin(dLon / 2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return R * c;
  };

  const formatDistance = (km) => {
    if (km == null) return '';
    if (km < 1) return `${Math.round(km * 1000)} m`;
    return `${km.toFixed(1)} km`;
  };

  const copyToClipboard = async (text) => {
    try {
      await navigator.clipboard.writeText(text);
      alert('Copied to clipboard');
    } catch (e) {
      console.warn('Copy failed', e);
    }
  };

  const [selectedId, setSelectedId] = useState(null);
  const [showFavoritesOnly, setShowFavoritesOnly] = useState(false);

  // This hook runs once to get the user's location
  useEffect(() => {
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          // On success, call the function to fetch hospitals
          fetchHospitals(position.coords.latitude, position.coords.longitude);
        },
        (err) => {
          // On failure (e.g., permission denied)
          setError("Please enable location access to find nearby hospitals.");
          setStatus('error');
        }
      );
    } else {
      setError("Geolocation is not supported by your browser.");
      setStatus('error');
    }
  }, []); // The empty array ensures this runs only once on mount

  // Save favorites to localStorage when they change
  useEffect(() => {
    localStorage.setItem('fav_hospitals', JSON.stringify(favorites));
  }, [favorites]);

  const refreshLocation = () => {
    setStatus('pending');
    setError('');
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (position) => fetchHospitals(position.coords.latitude, position.coords.longitude),
        () => {
          setError('Unable to retrieve your location.');
          setStatus('error');
        }
      );
    } else {
      setError('Geolocation is not supported by your browser.');
      setStatus('error');
    }
  };

  // Helper function to render content based on the status
  const renderContent = () => {
    switch (status) {
      case 'pending':
        return <p className="status-text">Getting your location...</p>;
      case 'loading':
        return <p className="status-text">Finding nearby hospitals...</p>;
      case 'error':
        return <p className="error-text">{error}</p>;
      case 'success':
        return hospitals.length > 0 ? (
          <div>
              <div className="locator-actions">
                <input
                  type="text"
                  placeholder="Filter hospitals by name..."
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  className="locator-search"
                />
                <button className="refresh-btn" onClick={refreshLocation}>Refresh location</button>
                <label className="fav-filter">
                  <input type="checkbox" checked={showFavoritesOnly} onChange={() => setShowFavoritesOnly(s => !s)} />
                  Favorites only
                </label>
              </div>

            <div className="hospitals-list">
              {hospitals
                .filter(h => h.name.toLowerCase().includes(query.toLowerCase()))
                .filter(h => !showFavoritesOnly || favorites.includes(h.id))
                .sort((a, b) => (b.is_recommended === true) - (a.is_recommended === true))
                .map((hospital, idx) => {
                  const id = hospital.id ?? idx;
                  const dist = (userLocation && hospital.lat && hospital.lng)
                    ? haversineDistance(userLocation.lat, userLocation.lng, hospital.lat, hospital.lng)
                    : null;
                  const isSelected = selectedId === id;
                  return (
                    <div
                      key={id}
                      className={`hospital-card ${hospital.is_recommended ? 'recommended' : ''} ${isSelected ? 'expanded' : ''}`}
                      role="button"
                      tabIndex={0}
                      onClick={() => setSelectedId(prev => prev === id ? null : id)}
                      onKeyDown={(e) => { if (e.key === 'Enter') setSelectedId(prev => prev === id ? null : id); }}
                    >
                      <div className="hospital-icon">
                        <i className="fa-solid fa-hospital"></i>
                      </div>
                      <div className="hospital-details">
                        <h4>
                          {hospital.name}
                          {hospital.is_recommended && <span className="recommended-badge">Recommended</span>}
                        </h4>
                        <p className="hospital-address">{hospital.address}</p>
                        {dist != null && <p className="hospital-distance">{formatDistance(dist)}</p>}

                        <div className="hospital-actions">
                          {hospital.phone && (
                            <a
                              href={`tel:${hospital.phone}`}
                              className="action-btn"
                              onClick={(e) => e.stopPropagation()}
                            >Call</a>
                          )}
                          {hospital.lat && hospital.lng && (
                            <a
                              href={`https://www.google.com/maps/dir/?api=1&destination=${hospital.lat},${hospital.lng}`}
                              target="_blank"
                              rel="noreferrer"
                              className="action-btn"
                              onClick={(e) => e.stopPropagation()}
                            >Directions</a>
                          )}
                          <button
                            className={`fav-btn ${favorites.includes(id) ? 'fav' : ''}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              setFavorites(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
                            }}
                          >
                            {favorites.includes(id) ? '★ Saved' : '☆ Save'}
                          </button>
                          <button
                            className="action-btn"
                            onClick={(e) => {
                              e.stopPropagation();
                              if (navigator.share) {
                                navigator.share({ title: hospital.name, text: hospital.address, url: window.location.href });
                              } else {
                                copyToClipboard(`${hospital.name} - ${hospital.address}`);
                              }
                            }}
                          >{navigator.share ? 'Share' : 'Copy'}</button>
                        </div>

                        {/* Expanded content */}
                          {isSelected && (
                          <div className="hospital-expanded">
                            {hospital.rating && <p>Rating: {hospital.rating} / 5</p>}
                            {hospital.opening_hours && <p>Hours: {hospital.opening_hours}</p>}
                            {hospital.notes && <p className="notes">{hospital.notes}</p>}
                            <div style={{ marginTop: 8 }}>
                              <button className="action-btn" onClick={(e) => { e.stopPropagation(); window.open(`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(hospital.name + ' ' + (hospital.address || ''))}`, '_blank'); }}>View on Map</button>
                              <button className="action-btn" onClick={(e) => { e.stopPropagation(); copyToClipboard(hospital.address || hospital.name); }}>Copy address</button>
                              <button className="book-appointment-btn" onClick={(e) => { e.stopPropagation(); if (onSelectHospital) onSelectHospital(hospital); }}>Book appointment</button>
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
            </div>
          </div>
        ) : (
          <p className="status-text">No hospitals found nearby.</p>
        );
      default:
        return null;
    }
  };

  return (
    <div className="locator-page">
      <div className="locator-header">
        <h2>Nearby Hospitals</h2>
        <p>Hospitals near your current location.</p>
      </div>
      {renderContent()}
    </div>
  );
}