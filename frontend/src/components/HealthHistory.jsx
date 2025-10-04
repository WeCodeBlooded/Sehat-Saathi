import React, { useState, useEffect } from 'react';

export default function HealthHistory({ backend, uid }) {
  const [records, setRecords] = useState([]);
  const [symptom, setSymptom] = useState('');
  const [date, setDate] = useState('');
  const [doctorNotes, setDoctorNotes] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [loadingList, setLoadingList] = useState(true);
  const [editingId, setEditingId] = useState(null);
  const [editSymptom, setEditSymptom] = useState('');
  const [editDate, setEditDate] = useState('');
  const [editNotes, setEditNotes] = useState('');

  const load = async () => {
    setLoadingList(true);
    try {
      const res = await fetch(`${backend}/get_health_history`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ uid }) });
      const data = await res.json();
      if (res.ok) setRecords(data.records || []); else setError(data.error || 'Failed to load');
    } catch (e) { setError(e.message); } finally { setLoadingList(false); }
  };
  useEffect(()=>{ load(); }, []);

  const add = async (e) => {
    e.preventDefault();
    if (date && new Date(date) > new Date(Date.now()+ 365*24*3600*1000)) { setError('Date cannot be more than 1 year in future'); return; }
    setLoading(true); setError('');
    const tempId = 'tmp-' + Date.now();
    const optimistic = { id: tempId, symptom, date, doctor_notes: doctorNotes, optimistic: true };
    setRecords(r => [optimistic, ...r]);
    try {
      const record = { symptom, date, doctor_notes: doctorNotes };
      const res = await fetch(`${backend}/add_health_record`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ uid, record }) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed');
      setRecords(r => r.map(x => x.id === tempId ? { ...x, id: data.id, optimistic:false }: x));
      setSymptom(''); setDate(''); setDoctorNotes('');
    } catch (e) { setError(e.message); setRecords(r => r.filter(x => x.id !== tempId)); }
    finally { setLoading(false); }
  };

  const startEdit = (r) => { setEditingId(r.id); setEditSymptom(r.symptom); setEditDate(r.date||''); setEditNotes(r.doctor_notes||''); };
  const cancelEdit = () => setEditingId(null);
  const saveEdit = async (id) => {
    const updates = { symptom: editSymptom, date: editDate, doctor_notes: editNotes };
    setRecords(rs => rs.map(x => x.id === id ? { ...x, ...updates, optimistic:true }: x));
    try {
      const res = await fetch(`${backend}/update_health_record`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ uid, id, updates }) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Update failed');
      setRecords(rs => rs.map(x => x.id === id ? { ...x, optimistic:false }: x));
      setEditingId(null);
    } catch (e) { setError(e.message); load(); }
  };
  const remove = async (id) => {
    const prev = records;
    setRecords(rs => rs.filter(x => x.id !== id));
    try {
      const res = await fetch(`${backend}/delete_health_record`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ uid, id }) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Delete failed');
    } catch (e) { setError(e.message); setRecords(prev); }
  };

  return (
    <div className="feature-card">
      <h2>Health History</h2>
      <form onSubmit={add} className="grid-form">
        <label>Symptom<input value={symptom} onChange={e=>setSymptom(e.target.value)} required placeholder="Fever" /></label>
        <label>Date<input type="date" value={date} onChange={e=>setDate(e.target.value)} required /></label>
        <label className="col-span-2">Doctor Notes<textarea value={doctorNotes} onChange={e=>setDoctorNotes(e.target.value)} placeholder="Prescribed paracetamol" rows={3} /></label>
        <div className="row-span-full">
          <button className="primary" disabled={loading}>{loading? 'Saving...':'Add Record'}</button>
        </div>
      </form>
      {error && <div className="alert error">{error}</div>}
      <h3>Past Records</h3>
      <div className="records-table-wrapper">
        {loadingList && <div className="skeleton-table">{Array.from({length:4}).map((_,i)=><div key={i} className="skeleton line" />)}</div>}
        {!loadingList && records.length === 0 && <div className="empty">No records yet.</div>}
        {!loadingList && records.length > 0 && (
          <table className="records-table">
            <thead><tr><th>Symptom</th><th>Date</th><th>Doctor Notes</th><th></th></tr></thead>
            <tbody>
              {records.map(r => (
                <tr key={r.id} className={r.optimistic? 'optimistic':''}>
                  <td>{editingId===r.id? <input value={editSymptom} onChange={e=>setEditSymptom(e.target.value)} /> : (r.symptom || r.record?.symptom)}</td>
                  <td>{editingId===r.id? <input type="date" value={editDate} onChange={e=>setEditDate(e.target.value)} /> : (r.date || r.record?.date)}</td>
                  <td>{editingId===r.id? <textarea rows={2} value={editNotes} onChange={e=>setEditNotes(e.target.value)} /> : (r.doctor_notes || r.record?.doctor_notes)}</td>
                  <td style={{whiteSpace:'nowrap'}}>
                    {editingId===r.id ? (
                      <>
                        <button type="button" className="ghost" onClick={()=>saveEdit(r.id)}>Save</button>
                        <button type="button" className="ghost" onClick={cancelEdit}>Cancel</button>
                      </>
                    ) : (
                      <>
                        <button type="button" className="ghost" onClick={()=>startEdit(r)}>Edit</button>
                        <button type="button" className="ghost" onClick={()=>remove(r.id)}>Delete</button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
