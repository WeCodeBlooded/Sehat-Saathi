import React, { useState } from 'react';

export default function Auth({ backend, onAuthSuccess }) {
  const [mode, setMode] = useState('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [role, setRole] = useState('patient');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [name, setName] = useState('');
  const [mobile, setMobile] = useState('');

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true); setError(''); setMessage('');
    try {
      const res = await fetch(`${backend}/${mode === 'login' ? 'login' : 'register'}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, role: mode==='register'? role : undefined, name: mode==='register'? name : undefined, mobile: mode==='register'? mobile : undefined })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed');
  setMessage(data.message || (mode === 'login' ? 'Logged in' : 'Registered'));
  if (data.role) localStorage.setItem('role', data.role);
  if (data.roleStatus) localStorage.setItem('roleStatus', data.roleStatus);
  if (data.patientId) localStorage.setItem('patientId', data.patientId);
  onAuthSuccess && onAuthSuccess(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-panel">
      <div className="segmented">
        <button className={mode==='login'? 'active':''} onClick={() => setMode('login')}>Login</button>
        <button className={mode==='register'? 'active':''} onClick={() => setMode('register')}>Register</button>
      </div>
      <form onSubmit={submit} className="stack gap-s">
        <input type="email" required placeholder="Email" value={email} onChange={e=>setEmail(e.target.value)} />
        <input type="password" required placeholder="Password" value={password} onChange={e=>setPassword(e.target.value)} />
        {mode==='register' && (
          <>
            <input type="text" placeholder="Full Name" value={name} onChange={e=>setName(e.target.value)} required />
            <input type="tel" placeholder="Mobile Number" value={mobile} onChange={e=>setMobile(e.target.value)} required pattern="[0-9+\-() ]{7,}" />
            <div className="row" style={{gap:12}}>
              <label style={{flex:1}}>
                <span style={{fontSize:12,fontWeight:600,letterSpacing:.5}}>Role</span>
                <select value={role} onChange={e=>setRole(e.target.value)} style={{marginTop:4}}>
                  <option value="patient">Patient</option>
                  <option value="doctor">Doctor</option>
                </select>
              </label>
            </div>
          </>
        )}
        <button disabled={loading} className="primary" type="submit">{loading? 'Please wait...': mode==='login'? 'Login':'Create Account'}</button>
      </form>
      {error && <div className="alert error">{error}</div>}
      {message && <div className="alert success">{message}</div>}
    </div>
  );
}
