import React, { useState, useEffect } from 'react';

const SPECIALTIES = ['cardiology','dermatology','neurology','orthopedics','pediatrics','ent','ophthalmology','general'];

export default function TeleCounselling({ backend, uid }) {
  const [speciality, setSpeciality] = useState('general');
  const [date, setDate] = useState('');
  const [timeSlot, setTimeSlot] = useState('10:00 AM');
  const [loading, setLoading] = useState(false);
  const [appointments, setAppointments] = useState([]);
  const [error, setError] = useState('');
  const [loadingList, setLoadingList] = useState(true);
  const [editingId, setEditingId] = useState(null);
  const [editTime, setEditTime] = useState('');
  const [editDate, setEditDate] = useState('');

  const load = async () => {
    setLoadingList(true);
    try {
      const res = await fetch(`${backend}/get_appointments`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ uid }) });
      const data = await res.json();
      if (res.ok) setAppointments(data.appointments || []); else setError(data.error || 'Failed to load');
    } catch (e) { setError(e.message); } finally { setLoadingList(false); }
  };
  useEffect(()=>{ load(); }, []);

  const schedule = async (e) => {
    e.preventDefault();
    if (date && new Date(date) < new Date().setHours(0,0,0,0)) { setError('Date must be today or future'); return; }
    setLoading(true); setError('');
    // Optimistic append
    const tempId = 'tmp-' + Date.now();
    const optimistic = { id: tempId, doctor_name: 'Assigning...', speciality, date, time_slot: timeSlot, optimistic: true };
    setAppointments(a => [optimistic, ...a]);
    try {
      const res = await fetch(`${backend}/schedule_appointment`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ uid, appointment: { speciality, date, time_slot: timeSlot } }) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed');
      // Replace optimistic
      setAppointments(a => a.map(x => x.id === tempId ? { ...x, id: data.id, optimistic: false } : x));
      setDate('');
    } catch (e) {
      setError(e.message);
      setAppointments(a => a.filter(x => x.id !== tempId));
    } finally { setLoading(false); }
  };

  const startEdit = (a) => {
    setEditingId(a.id); setEditTime(a.time_slot); setEditDate(a.date||'');
  };
  const cancelEdit = () => { setEditingId(null); };
  const saveEdit = async (id) => {
    if (editDate && new Date(editDate) < new Date().setHours(0,0,0,0)) { setError('Date must be today or future'); return; }
  const updates = { time_slot: editTime, date: editDate }; // doctor not editable after assignment
    // Optimistic
    setAppointments(a => a.map(x => x.id === id ? { ...x, ...updates, optimistic: true } : x));
    try {
      const res = await fetch(`${backend}/update_appointment`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ uid, id, updates }) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Update failed');
      setAppointments(a => a.map(x => x.id === id ? { ...x, optimistic: false } : x));
      setEditingId(null);
    } catch (e) {
      setError(e.message); load();
    }
  };
  const remove = async (id) => {
    const prev = appointments;
    setAppointments(a => a.filter(x => x.id !== id));
    try {
      const res = await fetch(`${backend}/delete_appointment`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ uid, id }) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Delete failed');
    } catch (e) { setError(e.message); setAppointments(prev); }
  };

  return (
    <div className="feature-card">
      <h2>Tele-Counselling Scheduler</h2>
      <form onSubmit={schedule} className="grid-form">
        <label>
          Speciality
          <select value={speciality} onChange={e=>setSpeciality(e.target.value)}>
            {SPECIALTIES.map(s => <option key={s} value={s}>{s.charAt(0).toUpperCase()+s.slice(1)}</option>)}
          </select>
        </label>
        <label>
          Date
          <input type="date" value={date} onChange={e=>setDate(e.target.value)} required />
        </label>
        <label>
          Time Slot
          <select value={timeSlot} onChange={e=>setTimeSlot(e.target.value)}>
            {['9:00 AM','10:00 AM','11:00 AM','2:00 PM','4:00 PM','6:00 PM'].map(t=> <option key={t}>{t}</option>)}
          </select>
        </label>
        <div className="row-span-full">
          <button className="primary" disabled={loading || !date}>{loading? 'Scheduling...':'Schedule'}</button>
        </div>
      </form>
      {error && <div className="alert error">{error}</div>}
      <h3>Upcoming Appointments</h3>
      <div className="list">
        {loadingList && <div className="skeleton-list">{Array.from({length:3}).map((_,i)=><div key={i} className="skeleton line" />)}</div>}
        {!loadingList && appointments.length === 0 && <div className="empty">No appointments scheduled yet.</div>}
        {!loadingList && appointments.map(a => (
          <div key={a.id} className={`list-item ${a.optimistic? 'optimistic':''}`}>
            {editingId === a.id ? (
              <div className="edit-block">
                <input type="date" value={editDate} onChange={e=>setEditDate(e.target.value)} />
                <select value={editTime} onChange={e=>setEditTime(e.target.value)}>{['9:00 AM','10:00 AM','11:00 AM','2:00 PM','4:00 PM','6:00 PM'].map(t=> <option key={t}>{t}</option>)}</select>
                <div className="row" style={{marginTop:8}}>
                  <button type="button" className="secondary" onClick={()=>saveEdit(a.id)}>Save</button>
                  <button type="button" className="ghost" onClick={cancelEdit}>Cancel</button>
                </div>
              </div>
            ) : (
              <>
                <strong>{a.doctor_name}{a.speciality? ` (${a.speciality})`:''}</strong>
                <span>{a.date} • {a.time_slot}</span>
                <div className="row" style={{marginTop:6}}>
                  <button type="button" className="ghost" onClick={()=>startEdit(a)}>Edit</button>
                  <button type="button" className="ghost" onClick={()=>remove(a.id)}>Delete</button>
                </div>
              </>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
