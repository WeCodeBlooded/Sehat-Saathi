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
		hospitals: { label: 'Locator', icon: '🗺️' },
		patient_overview: { label: 'Patients Health', icon: '📂' }
	}
};
function PatientHistoryOverview({ backend, uid, role, notify }) {
	const [query, setQuery] = useState('');
	const [loading, setLoading] = useState(false);
	const [patients, setPatients] = useState([]);
	const [expanded, setExpanded] = useState(null);
	const load = async () => {
		setLoading(true);
		try {
			const res = await fetch(`${backend}/patient_history_overview`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ doctor_uid: uid, query }) });
			const data = await res.json();
			if (!res.ok) throw new Error(data.error || 'Load failed');
			setPatients(data.patients||[]);
		} catch(e) { notify && notify(e.message,'error'); }
		finally { setLoading(false); }
	};
	useEffect(()=>{ if (role==='doctor') load(); }, []); // auto load for doctors
	const search = () => load();
	return (
		<div className="feature-card">
			<h2>Patients Health Overview</h2>
			<div className="row" style={{gap:8, marginBottom:10}}>
				<input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search by ID, name or email" onKeyDown={e=>{if(e.key==='Enter') search();}} />
				<button className="secondary" onClick={search} disabled={loading}>{loading? '...' : 'Search'}</button>
			</div>
			<div className="list" style={{maxHeight: role==='doctor'? 420: 320, overflow:'auto'}}>
				{loading && <div className="skeleton-list">{Array.from({length:4}).map((_,i)=><div key={i} className="skeleton line" />)}</div>}
				{!loading && patients.length===0 && <div className="empty">No patients match.</div>}
				{patients.map(p => (
					<div key={p.uid} className="list-item" style={{flexDirection:'column',alignItems:'stretch'}}>
						<div className="row" style={{justifyContent:'space-between',width:'100%'}}>
							<div style={{display:'flex',gap:16,fontSize:'.7rem',fontFamily:'monospace'}}>
								<span>{p.patient_id || '—'}</span>
								<span>{p.display_name || 'Unnamed'}</span>
								<span>{p.email}</span>
							</div>
							<button className="ghost small" onClick={()=> setExpanded(expanded===p.uid? null : p.uid)}>{expanded===p.uid? 'Hide' : 'View'}</button>
						</div>
						{expanded===p.uid && (
							<div className="stack gap-s" style={{marginTop:8}}>
								{p.history.length===0 && <div className="empty" style={{fontSize:'.6rem'}}>No recent records.</div>}
								{p.history.map(h => (
									<div key={h.id} className="mini-card" style={{fontSize:'.6rem'}}>
										<strong>{h.symptom || h.diagnosis || 'Record'}</strong>
										{h.summary_excerpt && <div className="excerpt">{h.summary_excerpt}</div>}
										{h.doctor_notes && <div className="notes">Notes: {h.doctor_notes}</div>}
									</div>
								))}
							</div>
						)}
					</div>
				))}
			</div>
			<p className="hint" style={{marginTop:8}}>{patients.length} patient(s) listed.</p>
		</div>
	);
}
function MyConsults({ backend, uid, notify }) {
	const [consults, setConsults] = useState([]);
	const [activeId, setActiveId] = useState(() => localStorage.getItem('lastAcceptedConsult') || null);
	const [messages, setMessages] = useState([]);
	const [attachments, setAttachments] = useState([]);
	const [uploadingAttachment, setUploadingAttachment] = useState(false);
	const [attachmentFile, setAttachmentFile] = useState(null);
	const [input, setInput] = useState('');
	const [loading, setLoading] = useState(true);
	const [msgLoading, setMsgLoading] = useState(false); // only used for initial load / switch
	const [initialMsgLoaded, setInitialMsgLoaded] = useState(false);
	const [showCloseModal, setShowCloseModal] = useState(false);
	const [closeRemarks, setCloseRemarks] = useState('');
	const [closePrescription, setClosePrescription] = useState('');
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
			setAttachments(data.attachments||[]);
			setInitialMsgLoaded(true);
		} catch (e) { /* swallow errors during background refresh */ }
		finally { if (!silent) setMsgLoading(false); }
	},[backend]);

	useEffect(()=>{
		if (!activeId) return;
		setInitialMsgLoaded(false);
		loadMessages(activeId, { silent:false }); // initial visible load
		// SSE attempt
		let es; let fallbackTimer;
		const startFallback = () => {
			fallbackTimer && clearInterval(fallbackTimer);
			fallbackTimer = setInterval(()=> loadMessages(activeId, { silent:true }), 3500);
		};
		try {
			es = new EventSource(`${backend.replace(/\/$/,'')}/consult_stream?request_id=${activeId}`);
			es.onmessage = ev => {
				try { const data = JSON.parse(ev.data||'{}'); if (Array.isArray(data.messages)) setMessages(data.messages); if (Array.isArray(data.attachments)) setAttachments(data.attachments); setInitialMsgLoaded(true); } catch(_){ }
			};
			es.addEventListener('heartbeat', ()=>{});
			es.addEventListener('end', ()=> { es && es.close(); startFallback(); });
			es.onerror = () => { es && es.close(); startFallback(); };
		} catch(e) { startFallback(); }
		return () => { es && es.close(); fallbackTimer && clearInterval(fallbackTimer); };
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

	const downloadAttachment = async (file) => {
		try {
			const resp = await fetch(`${backend}/get_consult_attachment`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ consult_id: activeId, filename: file.filename }) });
			const data = await resp.json();
			if (!resp.ok) throw new Error(data.error || 'Download failed');
			const bin = atob(data.content_base64);
			const bytes = new Uint8Array(bin.length); for (let i=0;i<bin.length;i++) bytes[i]=bin.charCodeAt(i);
			const blob = new Blob([bytes]);
			const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = file.filename; a.click();
			setTimeout(()=> URL.revokeObjectURL(a.href), 4000);
		} catch(e) { notify && notify(e.message,'error'); }
	};

	const uploadPrescriptionAttachment = async () => {
		if (!activeId || !attachmentFile) return;
		const f = attachmentFile;
		if (f.size > 2*1024*1024) { notify && notify('File too large (2MB max)','error'); return; }
		setUploadingAttachment(true);
		try {
			const toBase64 = file => new Promise((res,rej)=>{ const r=new FileReader(); r.onload=()=>res(r.result.split(',')[1]); r.onerror=rej; r.readAsDataURL(file); });
			const b64 = await toBase64(f);
			const resp = await fetch(`${backend}/upload_consult_attachment`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ consult_id: activeId, uid, role:'doctor', filename: f.name, content_base64: b64 }) });
			const data = await resp.json();
			if (!resp.ok) throw new Error(data.error || 'Upload failed');
			notify && notify('Prescription file uploaded','success');
			setAttachmentFile(null);
			loadMessages(activeId, { silent:true });
		} catch(e) { notify && notify(e.message,'error'); }
		finally { setUploadingAttachment(false); }
	};

	const closeConsult = async () => {
		if (!activeId) return;
		setShowCloseModal(true);
	};

	const submitCloseConsult = async () => {
		if (!activeId) return;
		try {
			const payload = { doctor_uid: uid, request_id: activeId, remarks: closeRemarks, prescription: closePrescription };
			const res = await fetch(`${backend}/close_consult`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
			const data = await res.json();
			if (!res.ok) throw new Error(data.error || 'Close failed');
			notify && notify('Consult closed','success');
			setConsults(cs => cs.filter(c=>c.id!==activeId));
			setActiveId(null);
			setMessages([]);
			setCloseRemarks(''); setClosePrescription(''); setShowCloseModal(false);
		} catch(e) { notify && notify(e.message,'error'); }
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
								{attachments.length>0 && (
									<div style={{display:'flex',flexWrap:'wrap',gap:6}}>
										{attachments.map(f => {
											const ext = (f.filename||'').toLowerCase().split('.').pop();
											const isImg = ['png','jpg','jpeg'].includes(ext);
											return (
												<button type="button" key={f.filename} className="chip" style={{fontSize:'.55rem'}} onClick={()=>downloadAttachment(f)}>{isImg? '🖼' : '📎'} {f.filename} {(!isImg)&&`(${Math.round((f.size||0)/1024)}kB)`}</button>
											);
										})}
									</div>
								)}
							</div>
							<div className="chat-input-row" style={{marginTop:8}}>
								<input value={input} onChange={e=>setInput(e.target.value)} placeholder="Type a message" onKeyDown={e=>{if(e.key==='Enter'){send();}}} />
								<button className="primary" type="button" onClick={send}>Send</button>
							</div>
							<div className="attachment-panel" style={{marginTop:6,display:'flex',alignItems:'center',gap:8,flexWrap:'wrap'}}>
								<input type="file" accept=".pdf,.png,.jpg,.jpeg,.txt" onChange={e=> setAttachmentFile(e.target.files?.[0]||null)} />
								<button className="secondary" type="button" disabled={!attachmentFile || uploadingAttachment} onClick={uploadPrescriptionAttachment}>{uploadingAttachment? 'Uploading...' : 'Upload Rx'}</button>
								{attachmentFile && <span style={{fontSize:'.55rem',opacity:.7}}>{attachmentFile.name}</span>}
							</div>
						</>
					)}
				</div>
				{showCloseModal && (
					<div className="modal-overlay" style={{position:'fixed',inset:0,background:'rgba(0,0,0,0.4)',display:'flex',alignItems:'center',justifyContent:'center',zIndex:100}}>
						<div className="card" style={{maxWidth:480,width:'100%',padding:'24px',display:'flex',flexDirection:'column',gap:16}}>
							<h3 style={{margin:0}}>Close Consult</h3>
							<textarea rows={3} placeholder="Doctor remarks" value={closeRemarks} onChange={e=>setCloseRemarks(e.target.value)} />
							<textarea rows={3} placeholder="Prescription details" value={closePrescription} onChange={e=>setClosePrescription(e.target.value)} />
							<div className="row" style={{gap:12,justifyContent:'flex-end'}}>
								<button className="ghost" type="button" onClick={()=>{setShowCloseModal(false);}}>Cancel</button>
								<button className="primary" type="button" onClick={submitCloseConsult}>Save & Close</button>
							</div>
						</div>
					</div>
				)}
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
	const [displayName, setDisplayName] = useState(localStorage.getItem('displayName') || '');
	const [mobile, setMobile] = useState(localStorage.getItem('mobile') || '');
	const [profileOpen, setProfileOpen] = useState(false);
	const [profileLoading, setProfileLoading] = useState(false);
	const [editingProfile, setEditingProfile] = useState(false);
	const [editName, setEditName] = useState('');
	const [editMobile, setEditMobile] = useState('');
	const [profileSaving, setProfileSaving] = useState(false);
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
			// Start a fresh chat session every login
			localStorage.removeItem('activeChatSession');
			setUid(info.uid);
			if (info.email) setEmail(info.email);
			localStorage.setItem('uid', info.uid);
			if (info.email) localStorage.setItem('email', info.email);
			if (info.role) { setRole(info.role); localStorage.setItem('role', info.role); }
			if (info.roleStatus) { setRoleStatus(info.roleStatus); localStorage.setItem('roleStatus', info.roleStatus); }
			if (info.patientId) { setPatientId(info.patientId); localStorage.setItem('patientId', info.patientId); }
			if (info.displayName) { setDisplayName(info.displayName); localStorage.setItem('displayName', info.displayName); }
			if (info.mobile) { setMobile(info.mobile); localStorage.setItem('mobile', info.mobile); }
		}
	}, []);

	const logout = () => {
		try { if (window.__lastChatAutoAnalyze) { window.__lastChatAutoAnalyze(); } } catch(e) {}
		localStorage.removeItem('uid');
		localStorage.removeItem('email');
		localStorage.removeItem('role');
		localStorage.removeItem('patientId');
		localStorage.removeItem('displayName');
		localStorage.removeItem('mobile');
		setUid('');
		setEmail('');
		setRole('patient');
		setRoleStatus('active');
		setPatientId('');
		setDisplayName('');
		setMobile('');
	};

	// Fetch profile after login to ensure we have latest details
	useEffect(() => {
		if (!uid) return;
		let cancelled = false;
		(async () => {
			try {
				setProfileLoading(true);
				const res = await fetch(`${BACKEND_URL}/get_profile`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ uid }) });
				const data = await res.json();
				if (!res.ok) throw new Error(data.error || 'Profile fetch failed');
				if (cancelled) return;
				if (data.display_name) { setDisplayName(data.display_name); localStorage.setItem('displayName', data.display_name); }
				if (data.patient_id) { setPatientId(data.patient_id); localStorage.setItem('patientId', data.patient_id); }
				if (data.mobile) { setMobile(data.mobile); localStorage.setItem('mobile', data.mobile); }
			} catch (e) {
				// silent fail for now
			} finally { setProfileLoading(false); }
		})();
		return () => { cancelled = true; };
	}, [uid]);

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
				return <HealthHistory backend={BACKEND_URL} uid={uid} role={role} notify={pushToast} />;
			case 'patient_overview':
				return <PatientHistoryOverview backend={BACKEND_URL} uid={uid} role={role} notify={pushToast} />;
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
						{uid ? (
							<button className="uid-chip" title="View profile" onClick={()=> setProfileOpen(true)}>
								{(role==='doctor'? 'Dr ' : '') + (displayName || email || 'User')}{role==='patient' && patientId? ` • ID ${patientId}`:''}
							</button>
						) : null}
					</div>
				</header>
				<div className="feature-area">
					{renderFeature()}
				</div>
				{profileOpen && uid && (
					<div className="modal-overlay" onClick={()=> { if(!profileSaving){ setProfileOpen(false); setEditingProfile(false);} }}>
						<div className="modal" onClick={e=>e.stopPropagation()}>
							<h3>Your Profile</h3>
							<div className="stack gap-s" style={{minWidth:300}}>
								{!editingProfile && <div><strong>Name: </strong>{displayName || <em style={{opacity:.6}}>Not set</em>}</div>}
								{editingProfile && <input type="text" value={editName} onChange={e=>setEditName(e.target.value)} placeholder="Full Name" />}
								<div><strong>Email: </strong>{email}</div>
								{patientId && <div><strong>Patient ID: </strong>{patientId}</div>}
								{!editingProfile && mobile && <div><strong>Mobile: </strong>{mobile}</div>}
								{editingProfile && <input type="tel" value={editMobile} onChange={e=>setEditMobile(e.target.value)} placeholder="Mobile" />}
								<div><strong>Role: </strong>{role} {role==='doctor' && <span style={{fontSize:'.65rem',opacity:.7}}>({roleStatus})</span>}</div>
								{profileLoading && <div style={{fontSize:'.65rem',opacity:.7}}>Refreshing…</div>}
								{profileSaving && <div style={{fontSize:'.6rem',color:'var(--accent)',opacity:.8}}>Saving…</div>}
							</div>
							<div className="row" style={{justifyContent:'space-between',marginTop:16}}>
								{!editingProfile && <button className="secondary" onClick={()=> { setEditingProfile(true); setEditName(displayName); setEditMobile(mobile); }}>Edit</button>}
								{editingProfile && (
									<button className="primary" disabled={profileSaving || !editName.trim() || !editMobile.trim()} onClick={async ()=>{
										setProfileSaving(true);
										try {
											const res = await fetch(`${BACKEND_URL}/update_profile`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ uid, display_name: editName.trim(), mobile: editMobile.trim() }) });
											const data = await res.json();
											if (!res.ok) throw new Error(data.error || 'Update failed');
											setDisplayName(data.display_name || editName.trim()); localStorage.setItem('displayName', data.display_name || editName.trim());
											setMobile(data.mobile || editMobile.trim()); localStorage.setItem('mobile', data.mobile || editMobile.trim());
											setEditingProfile(false);
										} catch (e) { alert(e.message); }
										finally { setProfileSaving(false); }
									}}>Save</button>
								)}
								{editingProfile && <button className="ghost" disabled={profileSaving} onClick={()=> { setEditingProfile(false); }}>Cancel</button>}
								<button className="secondary" disabled={profileSaving} onClick={()=> { setProfileOpen(false); setEditingProfile(false); }}>Close</button>
							</div>
						</div>
					</div>
				)}
						<div className="toast-layer">
							{toasts.map(t => (
								<div key={t.id} className={`toast ${t.type}`} onClick={()=>removeToast(t.id)}>{t.msg}</div>
							))}
						</div>
					</main>
		</div>
	);
}
