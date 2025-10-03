import React, { useEffect, useState } from 'react';
import './Appointments.css';

const API_URL = 'https://1d897642e66b.ngrok-free.app';

export default function Appointments({ selectedHospital }) {
  const [appointments, setAppointments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedDate, setSelectedDate] = useState('');
  const [selectedTime, setSelectedTime] = useState('');
  const [message, setMessage] = useState('');
  const [hospitalsNearby, setHospitalsNearby] = useState([]);
  const [hospitalId, setHospitalId] = useState(selectedHospital?.id || '');
  const [branches, setBranches] = useState([]);
  const [branch, setBranch] = useState('');
  const [hospitalSearch, setHospitalSearch] = useState('');

  const sampleBranches = [
    { code: 'genmed', name: 'General Medicine' },
    { code: 'ent', name: 'ENT (Ear, Nose, Throat)' },
    { code: 'derm', name: 'Dermatology / Skin Care' },
    { code: 'cardio', name: 'Cardiology' },
    { code: 'pedi', name: 'Pediatrics' }
  ];

  const sampleHospitals = [
    { id: 'h_demo_1', name: 'City General Hospital' },
    { id: 'h_demo_2', name: 'Sunrise Multispeciality' },
    { id: 'h_demo_3', name: 'Care & Cure Clinic' }
  ];

  const uid = localStorage.getItem('user_uid');

  const fetchAppointments = async () => {
    if (!uid) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/appointments/list`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ uid })
      });
      const data = await res.json();
      if (res.ok) setAppointments(data.appointments || []);
      else throw new Error(data.message || 'Failed to fetch');
    } catch (e) {
      console.error(e);
      setMessage('Could not load appointments');
    } finally { setLoading(false); }
  };

  useEffect(() => { fetchAppointments(); }, []);

  // If a hospital was passed from Locator, prefill selection and fetch branches
  useEffect(() => {
    if (selectedHospital) {
      setHospitalId(selectedHospital.id);
      // try to fetch branches for the selected hospital
      (async () => {
        try {
          const res = await fetch(`${API_URL}/hospital/branches`, { method: 'POST', headers: { 'Content-Type':'application/json' }, body: JSON.stringify({ hospitalId: selectedHospital.id }) });
          const data = await res.json();
          if (res.ok) setBranches(data.branches || []);
          else setBranches([]);
        } catch (e) { console.warn('branches error', e); setBranches([]); }
      })();
    }
  }, [selectedHospital]);

  // load nearby hospitals for user to choose from (optional)
  useEffect(() => {
    (async () => {
      try {
        const uid = localStorage.getItem('user_uid');
        const res = await fetch(`${API_URL}/hospitals/nearby`, { method: 'POST', headers: { 'Content-Type':'application/json' }, body: JSON.stringify({ uid }) });
        const data = await res.json();
        if (res.ok) setHospitalsNearby(data.hospitals || []);
      } catch (e) { /* ignore */ }
    })();
  }, []);

  const handleBook = async () => {
    if (!selectedDate || !selectedTime) { setMessage('Select date and time'); return; }
    if (!hospitalId) { setMessage('Select a hospital'); return; }
    try {
      const res = await fetch(`${API_URL}/appointments/book`, {
        method: 'POST', body: JSON.stringify({ uid, date: selectedDate, time: selectedTime, hospitalId, branch }), headers: { 'Content-Type': 'application/json' }
      });
      const data = await res.json();
      if (res.ok) {
        setMessage('Appointment booked');
        fetchAppointments();
      } else throw new Error(data.message || 'Booking failed');
    } catch (e) {
      console.error(e);
      setMessage(e.message || 'Booking failed');
    }
  };

  const handleCancel = async (id) => {
    try {
      const res = await fetch(`${API_URL}/appointments/cancel`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ uid, appointmentId: id })
      });
      const data = await res.json();
      if (res.ok) { setMessage('Cancelled'); fetchAppointments(); }
      else throw new Error(data.message || 'Cancel failed');
    } catch (e) { console.error(e); setMessage(e.message || 'Cancel failed'); }
  };

  return (
    <div className="appointments-container">
      <div className="appointments-header">
        <h3>Your Appointments</h3>
        <p className="muted">Book or cancel tele-counselling appointments</p>
      </div>

      <div className="appointments-body">
        <div className="book-panel">
          <h4>Book an appointment</h4>
          <label style={{ fontSize: 12, color: '#666' }}>Search / Select Hospital</label>
          <input value={hospitalSearch} onChange={e => setHospitalSearch(e.target.value)} placeholder="Type hospital name..." style={{ width:'100%', padding:8, borderRadius:6, marginTop:8, boxSizing:'border-box' }} />
          <div className="hospital-suggestions" style={{ marginTop:6 }}>
            {(hospitalsNearby.concat(sampleHospitals)).filter(h => h.name.toLowerCase().includes(hospitalSearch.toLowerCase())).slice(0,6).map(h => (
              <div key={h.id} className="suggestion" onClick={() => { setHospitalId(h.id); setHospitalSearch(h.name); setBranches(h.branches || sampleBranches); }}>
                {h.name}
              </div>
            ))}
          </div>
          <select value={hospitalId} onChange={e => setHospitalId(e.target.value)} style={{ width:'100%', padding:8, borderRadius:6, marginTop:8 }}>
            <option value="">-- Choose hospital --</option>
            {selectedHospital && <option value={selectedHospital.id}>{selectedHospital.name}</option>}
            {(hospitalsNearby.length ? hospitalsNearby : sampleHospitals).map(h => <option key={h.id} value={h.id}>{h.name}</option>)}
          </select>
          <label style={{ fontSize:12, color:'#666', marginTop:8 }}>Department / Branch</label>
          <select value={branch} onChange={e => setBranch(e.target.value)} style={{ width:'100%', padding:8, borderRadius:6, marginTop:8 }}>
            <option value="">-- Choose branch/field --</option>
            {branches.map(b => <option key={b.code} value={b.code}>{b.name}</option>)}
          </select>

          <input type="date" value={selectedDate} onChange={e => setSelectedDate(e.target.value)} style={{ marginTop:10 }} />
          <input type="time" value={selectedTime} onChange={e => setSelectedTime(e.target.value)} />
          <button onClick={handleBook} className="book-btn">Book</button>
          {message && <p className="message">{message}</p>}
          {hospitalsNearby && hospitalsNearby.length > 0 && (
            <div style={{ marginTop:12 }}>
              <div style={{ fontSize:12, color:'#666', marginBottom:6 }}>Quick select nearby</div>
              <div style={{ display:'flex', gap:8, flexWrap:'wrap' }}>
                {hospitalsNearby.slice(0,6).map(h => (
                  <button key={h.id} className="cancel-btn" onClick={() => { setHospitalId(h.id); setBranches(h.branches || []); }}>{h.name}</button>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="list-panel">
          <h4>Upcoming</h4>
          {loading ? <p>Loading...</p> : (
            appointments.length === 0 ? <p>No appointments</p> : (
              <ul className="appointments-list">
                {appointments.map(a => (
                  <li key={a.id} className="appointment-item">
                    <div>
                      <strong>{a.date} {a.time}</strong>
                      <div className="small">{a.provider || 'Tele-counselling'}</div>
                    </div>
                    <div>
                      <button className="cancel-btn" onClick={() => handleCancel(a.id)}>Cancel</button>
                    </div>
                  </li>
                ))}
              </ul>
            )
          )}
        </div>
      </div>
    </div>
  );
}
