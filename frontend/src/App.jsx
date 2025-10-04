import React, { useState, useEffect, useCallback, useRef } from 'react';
import './App.css';
import ChatBot from './components/ChatBot';
import TeleCounselling from './components/TeleCounselling';
import HospitalLocator from './components/HospitalLocator';
import HealthHistory from './components/HealthHistory';
import AuthPanel from './components/Auth';

const FEATURE_SETS = {
	patient: {
		chatbot: { label: 'Chatbot', icon: '💬' },
		tele: { label: 'Tele-Counselling', icon: '🗓️' },
		hospitals: { label: 'Hospital Locator', icon: '🗺️' },
		history: { label: 'Health History', icon: '📘' }
	},
	doctor: {
		doctor_dashboard: { label: 'Doctor Dashboard', icon: '🩺' },
		my_consults: { label: 'My Consults', icon: '💻' },
		chatbot: { label: 'Chatbot', icon: '💬' },
		hospitals: { label: 'Locator', icon: '🗺️' }
	}
};
function MyConsults({ backend, uid, notify }) {
	const [consults, setConsults] = useState([]);
	const [activeId, setActiveId] = useState(() => localStorage.getItem('lastAcceptedConsult') || null);
	const [messages, setMessages] = useState([]);
	const [input, setInput] = useState('');
	const [loading, setLoading] = useState(true);
	const [msgLoading, setMsgLoading] = useState(false); // only used for initial load / switch
	const [initialMsgLoaded, setInitialMsgLoaded] = useState(false);
	const pollRef = useRef(null);

	const loadConsults = useCallback(async ()=>{
		try {
			const res = await fetch(`${backend}/list_my_consults`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ doctor_uid: uid }) });
			const data = await res.json();
			if (!res.ok) throw new Error(data.error || 'Failed to load');
			setConsults(data.consults||[]);
		} catch (e) { notify && notify(e.message,'error'); }
		finally { setLoading(false); }
	},[backend,uid,notify]);

	useEffect(()=>{ loadConsults(); },[loadConsults]);

	// If we have a remembered consult id but it's not yet loaded (first fetch), select when arrives
	useEffect(()=>{
		if (activeId && consults.length>0 && !consults.find(c=>c.id===activeId)) {
			// If missing, clear
			setActiveId(null);
		}
	}, [consults, activeId]);

	const loadMessages = useCallback(async (cid, { silent=false } = {}) => {
		if (!cid) return;
		if (!silent) setMsgLoading(true);
		try {
			const res = await fetch(`${backend}/get_consult_messages`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ request_id: cid }) });
			const data = await res.json();
			if (!res.ok) throw new Error(data.error || 'Failed messages');
			setMessages(data.messages||[]);
			setInitialMsgLoaded(true);
		} catch (e) { /* swallow errors during background refresh */ }
		finally { if (!silent) setMsgLoading(false); }
	},[backend]);

	useEffect(()=>{
		if (!activeId) return;
		setInitialMsgLoaded(false);
		loadMessages(activeId, { silent:false }); // initial visible load
		pollRef.current && clearInterval(pollRef.current);
		pollRef.current = setInterval(()=> loadMessages(activeId, { silent:true }), 3500); // silent polls
		return () => { pollRef.current && clearInterval(pollRef.current); };
	},[activeId, loadMessages]);

	const send = async () => {
		if (!input.trim() || !activeId) return;
		const text = input.trim(); setInput('');
		// optimistic
		const temp = { id: 'temp'+Date.now(), role: 'doctor', text, ts: Date.now() };
		setMessages(m=>[...m,temp]);
		try {
			const res = await fetch(`${backend}/send_consult_message`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ request_id: activeId, uid, role:'doctor', text }) });
			if (!res.ok) {
				const data = await res.json();
				throw new Error(data.error || 'Send failed');
			}
			// Reload full list to replace temp with stored ordering
			loadMessages(activeId);
		} catch (e) { notify && notify(e.message,'error'); }
	};

	const closeConsult = async () => {
		if (!activeId) return;
		if (!window.confirm('Close this consult? This will end the chat.')) return;
		try {
			const res = await fetch(`${backend}/close_consult`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ doctor_uid: uid, request_id: activeId }) });
			const data = await res.json();
			if (!res.ok) throw new Error(data.error || 'Close failed');
			notify && notify('Consult closed','success');
			// remove from list and clear selection
			setConsults(cs => cs.filter(c=>c.id!==activeId));
			setActiveId(null);
			setMessages([]);
		} catch (e) { notify && notify(e.message,'error'); }
	};

	return (
		<div className="feature-card">
			<h2>My Active Consults</h2>
			<div className="row" style={{alignItems:'flex-start',gap:24,width:'100%'}}>
				<div style={{flex:1,minWidth:240}}>
					<div className="row" style={{justifyContent:'space-between'}}>
						<strong style={{fontSize:'.8rem'}}>Accepted ({consults.length})</strong>
						<button className="ghost small" onClick={loadConsults}>↻</button>
					</div>
					<div className="list" style={{maxHeight:340,overflow:'auto',marginTop:8}}>
						{loading && <div className="skeleton-list">{Array.from({length:3}).map((_,i)=><div className="skeleton line" key={i} />)}</div>}
						{!loading && consults.length===0 && <div className="empty">No active consults.</div>}
						{consults.map(c => (
							<button key={c.id} className={`list-item ${activeId===c.id? 'active':''}`} style={{textAlign:'left'}} onClick={()=> setActiveId(c.id)}>
								<strong>{c.patient_id? 'ID '+c.patient_id : c.patient_uid?.slice(0,6)+'…'}</strong>
								<span style={{fontSize:'.6rem',opacity:.7}}>{c.summary?.slice(0,80)}</span>
							</button>
						))}
					</div>
				</div>
				<div style={{flex:2,display:'flex',flexDirection:'column'}}>
					{!activeId && <div className="empty" style={{flex:1}}>Select a consult to chat.</div>}
					{activeId && (
						<>
							<div className="row" style={{justifyContent:'space-between',marginBottom:4}}>
								<strong style={{fontSize:'.75rem'}}>Consult: {activeId.slice(0,8)}…</strong>
								<button className="ghost small" onClick={closeConsult}>Close</button>
							</div>
							<div className="chat-window enhanced" style={{minHeight:300}}>
								{messages.length===0 && !msgLoading && initialMsgLoaded && <div className="bubble bot" style={{opacity:.6}}>No messages yet.</div>}
								{messages.map(m => (
									<div key={m.id} className={`bubble ${m.role==='doctor'? 'user':'bot'}`}>{m.text}</div>
								))}
								{msgLoading && !initialMsgLoaded && <div className="bubble bot loading">Loading…</div>}
							</div>
							<div className="chat-input-row" style={{marginTop:8}}>
								<input value={input} onChange={e=>setInput(e.target.value)} placeholder="Type a message" onKeyDown={e=>{if(e.key==='Enter'){send();}}} />
								<button className="primary" type="button" onClick={send}>Send</button>
							</div>
						</>
					)}
				</div>
			</div>
			<p className="hint">Polling every 3.5s. Replace with real-time listeners in production.</p>
		</div>
	);
}

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'http://localhost:5000';

function DoctorDashboard({ backend, uid, notify }) {
	const [appointments, setAppointments] = useState([]);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState('');
	const [openConsults, setOpenConsults] = useState([]);
	const [consultLoading, setConsultLoading] = useState(false);
	const [accepting, setAccepting] = useState(null);
	const [patientQuery, setPatientQuery] = useState('');
	const [patientResults, setPatientResults] = useState([]);
	const [searchingPatients, setSearchingPatients] = useState(false);
		const [viewingPatient, setViewingPatient] = useState(null); // holds fetched patient history object
		const [viewLoading, setViewLoading] = useState(false);

	useEffect(()=>{
		const load = async () => {
			try {
				const res = await fetch(`${backend}/doctor_appointments`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ uid }) });
				const data = await res.json();
				if (!res.ok) throw new Error(data.error || 'Failed');
				setAppointments(data.appointments||[]);
			} catch (e) { setError(e.message); } finally { setLoading(false); }
		}; load();
	}, [backend, uid]);

	const loadConsults = useCallback(async () => {
		setConsultLoading(true);
		try {
			const res = await fetch(`${backend}/list_open_consults`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ doctor_uid: uid }) });
			const data = await res.json();
			if (!res.ok) throw new Error(data.error || 'Failed to load consults');
			setOpenConsults(data.requests||[]);
		} catch (e) { notify && notify(e.message,'error'); }
		finally { setConsultLoading(false); }
	}, [backend, uid, notify]);

	useEffect(()=>{ loadConsults(); }, [loadConsults]);

	const acceptConsult = async (id) => {
		setAccepting(id);
		try {
			const res = await fetch(`${backend}/accept_consult`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ doctor_uid: uid, request_id: id }) });
			const data = await res.json();
			if (!res.ok) throw new Error(data.error || 'Accept failed');
			notify && notify('Consult accepted – switch to My Consults to chat','success');
			localStorage.setItem('lastAcceptedConsult', id);
			setOpenConsults(cs => cs.filter(c=>c.id!==id));
		} catch (e) { notify && notify(e.message,'error'); }
		finally { setAccepting(null); }
	};

	const rejectConsult = async (id) => {
		if (!window.confirm('Skip this consult request? It will remain available for other doctors.')) return;
		try {
			const res = await fetch(`${backend}/reject_consult`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ doctor_uid: uid, request_id: id }) });
			const data = await res.json();
			if (!res.ok) throw new Error(data.error || 'Reject failed');
			notify && notify('Consult skipped','info');
			setOpenConsults(cs => cs.filter(c=>c.id!==id));
		} catch (e) { notify && notify(e.message,'error'); }
	};

	const searchPatients = async () => {
		setSearchingPatients(true);
		try {
			const res = await fetch(`${backend}/search_patients`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ doctor_uid: uid, query: patientQuery }) });
			const data = await res.json();
			if (!res.ok) throw new Error(data.error || 'Search failed');
			setPatientResults(data.patients||[]);
		} catch (e) { notify && notify(e.message,'error'); }
		finally { setSearchingPatients(false); }
	};

		const viewPatient = async (p) => {
			setViewLoading(true); setViewingPatient(null);
			try {
				const res = await fetch(`${backend}/get_patient_history`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ doctor_uid: uid, patient_id: p.patient_id, patient_uid: p.uid }) });
				const data = await res.json();
				if (!res.ok) throw new Error(data.error || 'Fetch failed');
				setViewingPatient(data);
			} catch (e) { notify && notify(e.message,'error'); }
			finally { setViewLoading(false); }
		};

	return (
		<div className="feature-card">
			<h2>Doctor Dashboard</h2>
			{error && <div className="alert error">{error}</div>}
			<section className="stack gap-m">
				<div>
					<h3 style={{marginTop:0}}>Open Consult Requests</h3>
					<button className="ghost small" onClick={loadConsults} disabled={consultLoading}>{consultLoading? 'Refreshing...' : 'Refresh'}</button>
					{openConsults.length===0 && !consultLoading && <div className="empty">No open consults.</div>}
					<div className="list">
						{openConsults.map(req => (
							<div key={req.id} className="list-item" style={{alignItems:'flex-start'}}>
								<div className="col">
									<strong>{req.patient_id? 'ID '+req.patient_id : req.patient_uid?.slice(0,6)+'…'}</strong>
									<div style={{fontSize:'.65rem',opacity:.7}}>{req.patient_email}</div>
									<div style={{fontSize:'.7rem',marginTop:4}}>{req.summary}</div>
								</div>
								<div className="col" style={{gap:4}}>
									<button className="primary small" disabled={accepting===req.id} onClick={()=>acceptConsult(req.id)}>{accepting===req.id? 'Accepting...' : 'Accept'}</button>
									<button className="ghost small" onClick={()=>rejectConsult(req.id)}>Reject</button>
								</div>
							</div>
						))}
					</div>
				</div>
				<div>
					<h3>Scheduled Appointments</h3>
					{loading && <div className="skeleton-list">{Array.from({length:4}).map((_,i)=><div key={i} className="skeleton line" />)}</div>}
					{!loading && appointments.length===0 && <div className="empty">No appointments yet.</div>}
					<div className="list">
						{appointments.map(a => (
							<div key={a.id} className="list-item">
								<strong>{a.patient_uid?.slice(0,6)}…</strong>
								<span>{a.date} • {a.time_slot}</span>
								<span style={{fontSize:'.6rem',opacity:.7}}>Assigned as: {a.doctor_name}</span>
							</div>
						))}
					</div>
				</div>
				<div>
					<h3>Patient Records Access</h3>
					<div className="row" style={{gap:8, marginBottom:8}}>
						<input placeholder="Search by email or patient ID" value={patientQuery} onChange={e=>setPatientQuery(e.target.value)} />
						<button className="secondary" disabled={searchingPatients} onClick={searchPatients}>{searchingPatients? '...' : 'Search'}</button>
					</div>
					{patientResults.length>0 && (
						<div className="list">
							{patientResults.map(p => (
								<div key={p.uid} className="list-item" style={{flexDirection:'row',justifyContent:'space-between'}}>
									<div>
										<strong>{p.email}</strong>
										<div style={{fontSize:'.65rem',opacity:.7}}>ID {p.patient_id}</div>
									</div>
														<button className="ghost small" onClick={()=>viewPatient(p)} disabled={viewLoading}>{viewLoading? '...' : 'View'}</button>
								</div>
							))}
						</div>
					)}
				</div>
									{viewingPatient && (
										<div className="modal-overlay" onClick={()=>setViewingPatient(null)}>
											<div className="modal" onClick={e=>e.stopPropagation()}>
												<h3>Patient History (ID {viewingPatient.patient_id})</h3>
												<div style={{maxHeight:'40vh',overflow:'auto'}} className="stack gap-s">
													<strong>Health Records ({viewingPatient.health_history.length})</strong>
													{viewingPatient.health_history.map(r => (
														<div key={r.id} className="mini-card">
															<div><b>{r.symptom || r.diagnosis || 'Symptom'}</b></div>
															{r.summary_excerpt && <div className="excerpt">{r.summary_excerpt}</div>}
															{r.doctor_notes && <div className="notes">Notes: {r.doctor_notes}</div>}
														</div>
													))}
													<strong>Chat Sessions ({viewingPatient.chat_sessions.length})</strong>
													{viewingPatient.chat_sessions.map(s => (
														<div key={s.id} className="mini-card">
															<div><b>{s.major_issue || 'Session'}</b> {s.confidence!=null && <span style={{fontSize:'.65rem',opacity:.7}}>({(s.confidence*100).toFixed(1)}%)</span>}</div>
															{s.summary_excerpt && <div className="excerpt">{s.summary_excerpt}</div>}
															<div style={{fontSize:'.6rem',opacity:.6}}>Messages: {s.message_count || '?'}{s.analyzed_at? ' • analyzed':''}</div>
														</div>
													))}
												</div>
												<div className="row" style={{justifyContent:'flex-end',marginTop:12}}>
													<button className="secondary" onClick={()=>setViewingPatient(null)}>Close</button>
												</div>
											</div>
										</div>
									)}
			</section>
		</div>
	);
}

export default function App() {
	const [active, setActive] = useState('chatbot');
	const [uid, setUid] = useState(localStorage.getItem('uid') || '');
	const [email, setEmail] = useState(localStorage.getItem('email') || '');
	const [role, setRole] = useState(localStorage.getItem('role') || 'patient');
	const [roleStatus, setRoleStatus] = useState(localStorage.getItem('roleStatus') || 'active');
	const [patientId, setPatientId] = useState(localStorage.getItem('patientId') || '');
		const [dark, setDark] = useState(() => {
			const stored = localStorage.getItem('theme');
			if (stored) return stored === 'dark';
			return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
		});
		const [collapsedNav, setCollapsedNav] = useState(() => localStorage.getItem('navCollapsed') === '1');
		const [toasts, setToasts] = useState([]);
		const toastIdRef = useRef(0);

		const pushToast = useCallback((msg, type='info', ttl=4000) => {
			const id = ++toastIdRef.current;
			const t = { id, msg, type };
			setToasts(ts => [...ts, t]);
			setTimeout(()=> setToasts(ts => ts.filter(x=>x.id!==id)), ttl);
		}, []);

		const removeToast = id => setToasts(ts => ts.filter(t => t.id !== id));

	const handleAuth = useCallback((info) => {
		if (info?.uid) {
			setUid(info.uid);
			if (info.email) setEmail(info.email);
			localStorage.setItem('uid', info.uid);
			if (info.email) localStorage.setItem('email', info.email);
			if (info.role) { setRole(info.role); localStorage.setItem('role', info.role); }
			if (info.roleStatus) { setRoleStatus(info.roleStatus); localStorage.setItem('roleStatus', info.roleStatus); }
			if (info.patientId) { setPatientId(info.patientId); localStorage.setItem('patientId', info.patientId); }
		}
	}, []);

	const logout = () => {
		localStorage.removeItem('uid');
		localStorage.removeItem('email');
		localStorage.removeItem('role');
		localStorage.removeItem('patientId');
		setUid('');
		setEmail('');
		setRole('patient');
		setRoleStatus('active');
		setPatientId('');
	};

		useEffect(() => {
			document.documentElement.dataset.theme = dark ? 'dark' : 'light';
			localStorage.setItem('theme', dark ? 'dark' : 'light');
		}, [dark]);

		useEffect(()=> { localStorage.setItem('navCollapsed', collapsedNav ? '1':'0'); }, [collapsedNav]);

	const renderFeature = () => {
		if (!uid) {
			return (
				<div className="card intro-card">
					<h2>Welcome to Sehat Saathi</h2>
					<p>Please register or login to access features.</p>
					<AuthPanel backend={BACKEND_URL} onAuthSuccess={handleAuth} />
				</div>
			);
		}
		const features = FEATURE_SETS[role] || FEATURE_SETS.patient;
		if (role==='doctor' && roleStatus==='pending') {
			return (
				<div className="card intro-card">
					<h2>Verification Pending</h2>
					<p>Your doctor account is awaiting admin approval. You currently have limited access.</p>
					<p style={{fontSize:'0.7rem',opacity:.7}}>You can still use the Chatbot and Hospital Locator.</p>
				</div>
			);
		}
		switch (active) {
			case 'doctor_dashboard':
				return <DoctorDashboard backend={BACKEND_URL} uid={uid} notify={pushToast} />;
			case 'my_consults':
				return <MyConsults backend={BACKEND_URL} uid={uid} notify={pushToast} />;
			case 'chatbot':
				return <ChatBot backend={BACKEND_URL} uid={uid} role={role} notify={pushToast} onNavigateHistory={() => setActive('history')} />;
			case 'tele':
				return <TeleCounselling backend={BACKEND_URL} uid={uid} notify={pushToast} />;
			case 'hospitals':
				return <HospitalLocator backend={BACKEND_URL} uid={uid} notify={pushToast} />;
			case 'history':
				return <HealthHistory backend={BACKEND_URL} uid={uid} notify={pushToast} />;
			default:
				return null;
		}
	};

	return (
		<div className="app-shell">
			<aside className={`nav ${collapsedNav ? 'collapsed' : ''}`}>
				<div className="brand" onClick={() => setActive('chatbot')}>
					<span className="logo">🩺</span>
					<span className="title">Sehat Saathi</span>
				</div>
				<nav>
					{Object.entries(FEATURE_SETS[role] || FEATURE_SETS.patient).map(([k, v]) => (
						<button
							key={k}
							className={`nav-item ${active === k ? 'active' : ''}`}
							onClick={() => setActive(k)}
						>
							<span className="icon" aria-hidden>{v.icon}</span>
							<span className="text">{v.label}</span>
						</button>
					))}
				</nav>
				<div className="grow" />
				<div className="nav-footer">
								<button className="secondary" onClick={() => setDark(d => !d)}>
						{dark ? '🌞 Light' : '🌙 Dark'}
					</button>
					{uid ? (
						<button className="secondary" onClick={logout}>Logout</button>
					) : null}
								<button className="ghost small" onClick={() => setCollapsedNav(c => !c)}>
						{collapsedNav ? '➡️' : '⬅️'}
					</button>
				</div>
			</aside>
			<main className="main-area">
				<header className="topbar">
					<div className="breadcrumbs">{(FEATURE_SETS[role] || FEATURE_SETS.patient)[active]?.label}</div>
					<div className="user-info">
						{uid ? <span className="uid-chip" title={uid}>{(role==='doctor'?'Dr ':'') + (email || 'User')}{role==='patient' && patientId? ` • ID ${patientId}`:''}</span> : null}
					</div>
				</header>
				<div className="feature-area">
					{renderFeature()}
				</div>
						<div className="toast-layer">
							{toasts.map(t => (
								<div key={t.id} className={`toast ${t.type}`} onClick={()=>removeToast(t.id)}>{t.msg}</div>
							))}
						</div>
					</main>
		</div>
	);
}
