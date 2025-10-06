import React, { useState, useRef, useEffect } from 'react';

// ChatBot now derives speaker role from parent (patient/doctor) instead of an in-component selector
export default function ChatBot({ backend, uid, notify, onNavigateHistory, role }) {
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [sessionIssue, setSessionIssue] = useState(null);
  const [sessionConfidence, setSessionConfidence] = useState(null);
  const [sessionEvidence, setSessionEvidence] = useState([]);
  const [pendingIssue, setPendingIssue] = useState(null); // analysis result awaiting confirmation
  const [pendingMeta, setPendingMeta] = useState(null);
  const [consultRequestId, setConsultRequestId] = useState(null);
  const [consultLoading, setConsultLoading] = useState(false);
  const [consultStatus, setConsultStatus] = useState(null); // open | accepted
  const [consultMessages, setConsultMessages] = useState([]);
  const [attachments, setAttachments] = useState([]);
  const [attachmentFile, setAttachmentFile] = useState(null);
  const [uploadingAttachment, setUploadingAttachment] = useState(false);
  const consultPollRef = useRef(null);
  const [consultMsgInput, setConsultMsgInput] = useState('');
  const bottomRef = useRef(null);
  const [sessionId, setSessionId] = useState(()=> localStorage.getItem('activeChatSession') || null);
  const restoringRef = useRef(false);
  const [sessions, setSessions] = useState([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [showSessions, setShowSessions] = useState(false);
  const [loadingSessionSwitch, setLoadingSessionSwitch] = useState(false);
  const [renamingId, setRenamingId] = useState(null);
  const [renameValue, setRenameValue] = useState('');

  const send = async (e) => {
    e.preventDefault();
    if (!input.trim()) return;
  const userMsg = { role: role === 'doctor' ? 'doctor' : 'user', text: input.trim(), ts: Date.now() };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setLoading(true);
    try {
      const res = await fetch(`${backend}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ uid, message: userMsg.text, session_id: sessionId })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Chat failed');
      setMessages(prev => [...prev, { role: 'bot', text: data.message, lang: data.language, ts: Date.now() }]);
      if (data.session_id && data.session_id !== sessionId) {
        setSessionId(data.session_id);
        localStorage.setItem('activeChatSession', data.session_id);
      }
    } catch (err) {
      setMessages(prev => [...prev, { role: 'error', text: err.message, ts: Date.now() }]);
    } finally {
      setLoading(false);
    }
  };

  const analyzeSession = async () => {
    if (messages.length === 0) return;
    setAnalyzing(true); setPendingIssue(null); setSessionIssue(null);
    try {
  const payload = { uid, messages: messages.map(m => ({ role: m.role, text: typeof m.text === 'string' ? m.text.replace(/<[^>]+>/g,' ') : '' })), save: false, session_id: sessionId };
      const res = await fetch(`${backend}/analyze_chat_session`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Analysis failed');
      if (data.major_issue) {
        setPendingIssue(data.major_issue);
        setPendingMeta({ confidence: data.confidence, evidence: data.evidence_tokens, score: data.major_issue_score });
        notify && notify(`Analysis: ${data.major_issue} (confirm to save)`, 'info');
      } else if (data.error) {
        notify && notify(data.error,'error');
      }
    } catch (e) { notify && notify(e.message,'error'); }
    finally { setAnalyzing(false); }
  };

  const loadSessions = async () => {
    if (!uid) return;
    setSessionsLoading(true);
    try {
      const res = await fetch(`${backend}/list_chat_sessions`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ uid, limit: 30 }) });
      const data = await res.json();
      if (res.ok && Array.isArray(data.sessions)) {
        setSessions(data.sessions);
      }
    } catch(e) { /* silent */ }
    finally { setSessionsLoading(false); }
  };

  const switchToSession = async (sid) => {
    if (!sid) return;
    if (sid === sessionId) { setShowSessions(false); return; }
    setLoadingSessionSwitch(true);
    try {
      const res = await fetch(`${backend}/get_chat_session_messages`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ uid, session_id: sid }) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to load session');
      const restored = (data.messages||[]).map(m => ({ role: m.role || m.sender || 'user', text: m.text || m.message || '', ts: m.ts || Date.now() }));
      setMessages(restored);
      setSessionId(sid);
      localStorage.setItem('activeChatSession', sid);
      setSessionIssue(data.meta?.major_issue || null);
      setSessionConfidence(data.meta?.confidence || null);
      setSessionEvidence([]); // hide old evidence unless re-analyzed
      setPendingIssue(null); setPendingMeta(null);
      setShowSessions(false);
    } catch(e) {
      notify && notify(e.message,'error');
    } finally { setLoadingSessionSwitch(false); }
  };

  const startNewSession = () => {
    if (messages.length>0 && !window.confirm('Start a new session? Current chat will remain in history.')) return;
    setMessages([]);
    setSessionId(null);
    localStorage.removeItem('activeChatSession');
    setSessionIssue(null); setSessionConfidence(null); setSessionEvidence([]);
    setPendingIssue(null); setPendingMeta(null);
    notify && notify('New session started','info');
  };

  const beginRename = (s) => {
    setRenamingId(s.id);
    setRenameValue(s.title || '');
  };
  const submitRename = async (s) => {
    // Submit rename to backend; optimistic update after success
    if (!renameValue.trim()) { setRenamingId(null); return; }
    try {
      const res = await fetch(`${backend}/rename_chat_session`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ uid, session_id: s.id, title: renameValue.trim() }) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Rename failed');
      setSessions(sess => sess.map(x => x.id===s.id ? { ...x, title: data.title, title_auto: false } : x));
      if (sessionId === s.id) {
        // update current session title locally
      }
      setRenamingId(null);
    } catch(e) { notify && notify(e.message,'error'); }
  };
  const escalateToDoctor = async () => {
      if (role !== 'patient' || consultRequestId || messages.length===0) return;
      setConsultLoading(true);
      try {
        const payload = { uid, messages: messages.map(m => ({ role: m.role, text: m.text })) };
        const res = await fetch(`${backend}/request_consult`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Failed to request consult');
        setConsultRequestId(data.request_id);
      setConsultStatus('open');
        notify && notify('Consult request created. Awaiting doctor acceptance.','success');
      } catch (e) {
        notify && notify(e.message,'error');
      } finally {
        setConsultLoading(false);
      }
    };

  const loadConsultMessages = async (rid) => {
    if (!rid) return;
    try {
      const res = await fetch(`${backend}/get_consult_messages`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ request_id: rid }) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Fetch failed');
      setConsultStatus(data.status);
      setConsultMessages(data.messages||[]);
      // Also fetch attachments
      try {
        const ar = await fetch(`${backend}/list_consult_attachments`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ consult_id: rid }) });
        const ad = await ar.json();
        if (ar.ok && ad.files) setAttachments(ad.files);
      } catch(e) {/* ignore */}
    } catch (e) {
      // silently ignore to avoid toast spam
    }
  };

  // Start polling when a consult request exists
  useEffect(()=>{
    if (!consultRequestId) {
      consultPollRef.current && clearInterval(consultPollRef.current);
      return;
    }
    // initial immediate fetch
    loadConsultMessages(consultRequestId);
    consultPollRef.current && clearInterval(consultPollRef.current);
    consultPollRef.current = setInterval(()=> loadConsultMessages(consultRequestId), 3500);
    return () => { consultPollRef.current && clearInterval(consultPollRef.current); };
  }, [consultRequestId]);

  const sendConsultMessage = async () => {
    if (!consultRequestId || consultStatus !== 'accepted' || !consultMsgInput.trim()) return;
    const text = consultMsgInput.trim();
    setConsultMsgInput('');
    // optimistic
    setConsultMessages(ms => [...ms, { id: 'temp'+Date.now(), role: 'patient', text, ts: Date.now() }]);
    try {
      const res = await fetch(`${backend}/send_consult_message`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ request_id: consultRequestId, uid, role:'patient', text }) });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error || 'Failed to send');
      }
    } catch (e) {
      notify && notify(e.message,'error');
    }
  };

  const uploadAttachment = async () => {
    if (!consultRequestId || consultStatus !== 'accepted' || !attachmentFile) return;
    const f = attachmentFile;
    if (f.size > 2*1024*1024) { notify && notify('File too large (max 2MB)','error'); return; }
    setUploadingAttachment(true);
    try {
      const toBase64 = (file) => new Promise((res,rej)=>{ const r = new FileReader(); r.onload=()=>res(r.result.split(',')[1]); r.onerror=rej; r.readAsDataURL(file); });
      const b64 = await toBase64(f);
      const payload = { consult_id: consultRequestId, uid, role: 'patient', filename: f.name, content_base64: b64 };
      const resp = await fetch(`${backend}/upload_consult_attachment`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || 'Upload failed');
      notify && notify('File uploaded','success');
      setAttachmentFile(null);
      // refresh list
      const ar = await fetch(`${backend}/list_consult_attachments`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ consult_id: consultRequestId }) });
      const ad = await ar.json(); if (ar.ok && ad.files) setAttachments(ad.files);
    } catch(e) { notify && notify(e.message,'error'); }
    finally { setUploadingAttachment(false); }
  };

  const downloadAttachment = async (file) => {
    try {
      const resp = await fetch(`${backend}/get_consult_attachment`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ consult_id: consultRequestId, filename: file.filename }) });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || 'Download failed');
      const bin = atob(data.content_base64);
      const bytes = new Uint8Array(bin.length); for (let i=0;i<bin.length;i++) bytes[i]=bin.charCodeAt(i);
      const blob = new Blob([bytes]);
      const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = file.filename; a.click();
      setTimeout(()=> URL.revokeObjectURL(a.href), 4000);
    } catch(e) { notify && notify(e.message,'error'); }
  };

  const confirmSave = async () => {
    if (!pendingIssue) return;
    try {
  const res = await fetch(`${backend}/analyze_chat_session`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ uid, major_issue: pendingIssue, save: true, session_id: sessionId }) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Save failed');
      setSessionIssue(pendingIssue);
      setSessionConfidence(pendingMeta?.confidence || null);
      setSessionEvidence(pendingMeta?.evidence || []);
      setPendingIssue(null); setPendingMeta(null);
      notify && notify(`Saved: ${data.major_issue}`,'success');
    } catch (e) {
      notify && notify(e.message,'error');
    }
  };
  const cancelPending = () => { setPendingIssue(null); setPendingMeta(null); };

  const highlightedText = (text) => {
    if (!pendingMeta?.evidence) return text;
    return text.split(/(\b)/).map((part,i) => {
      const lower = part.toLowerCase();
      if (pendingMeta.evidence.includes(lower) && /[a-z]/i.test(part)) {
        return <mark key={i} className="evid-token">{part}</mark>;
      }
      return <React.Fragment key={i}>{part}</React.Fragment>;
    });
  };

  const looksLikeHtml = (str) => /<\s*(p|div|ul|li|strong|em|br)\b/i.test(str || '');
  const sanitizeHtml = (html) => {
    if (!html) return '';
    // Strip script/style and inline event handlers (very lightweight; backend is trusted)
    let safe = html.replace(/<script[\s\S]*?>[\s\S]*?<\/script>/gi,'')
                   .replace(/<style[\s\S]*?>[\s\S]*?<\/style>/gi,'')
                   .replace(/ on[a-zA-Z]+="[^"]*"/g,'')
                   .replace(/ on[a-zA-Z]+='[^']*'/g,'');
    return safe;
  };

  useEffect(()=>{ bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  // If user logs out then logs back in (uid change), force a new session regardless of stored value
  const prevUidRef = useRef(uid);
  useEffect(()=>{
    if (prevUidRef.current !== uid) {
      prevUidRef.current = uid;
      // new login: clear session & messages
      setSessionId(null);
      setMessages([]);
      localStorage.removeItem('activeChatSession');
      setSessionIssue(null); setSessionConfidence(null); setSessionEvidence([]);
      setPendingIssue(null); setPendingMeta(null);
    }
  }, [uid]);

  // Restore active session messages & active consult on mount
  useEffect(()=>{
    if (!uid) return;
    (async () => {
      try {
        if (sessionId && !restoringRef.current) {
          restoringRef.current = true;
          // fetch existing messages for this session
          const res = await fetch(`${backend}/get_chat_session_messages`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ uid, session_id: sessionId }) });
          const data = await res.json();
          if (res.ok && Array.isArray(data.messages)) {
            // Map backend message format to local format
            const restored = data.messages.map(m => ({ role: m.role || m.sender || 'user', text: m.text || m.message || '', ts: m.ts || Date.now() }));
            setMessages(restored);
          }
        }
      } catch(e) {/* silent */}
    })();
  }, [uid, sessionId, backend]);

  // Load session list on mount & when a new session id appears
  useEffect(()=>{ if (role==='patient') loadSessions(); }, [role, uid, sessionId]);

  useEffect(()=>{
    if (!uid) return;
    // Attempt to load active consult (open/accepted)
    (async () => {
      try {
        const res = await fetch(`${backend}/get_patient_active_consult`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ uid }) });
        const data = await res.json();
        if (res.ok && data.active) {
          setConsultRequestId(data.active.id);
          setConsultStatus(data.active.status);
          if (data.messages) setConsultMessages(data.messages);
        }
      } catch(e) {}
    })();
  }, [uid]);

  return (
    <div className="feature-card chatbot">
      <h2>Health Chat Assistant</h2>
      {role==='patient' && (
        <div className="row" style={{justifyContent:'space-between',marginBottom:4}}>
          <div className="row" style={{gap:6}}>
            <button type="button" className="ghost small" onClick={()=> setShowSessions(s=>!s)}>{showSessions? 'Hide Sessions' : 'Sessions'}</button>
            <button type="button" className="ghost small" onClick={loadSessions} disabled={sessionsLoading}>{sessionsLoading? '...' : '↻'}</button>
          </div>
          <button type="button" className="secondary small" onClick={startNewSession}>New Session</button>
        </div>
      )}
      {showSessions && role==='patient' && (
        <div className="session-list modern" style={{maxHeight:220,overflow:'auto',marginBottom:10}}>
          {sessionsLoading && <div className="skeleton-list">{Array.from({length:4}).map((_,i)=><div className="skeleton line" key={i} />)}</div>}
          {!sessionsLoading && sessions.length===0 && <div className="empty" style={{fontSize:'.7rem'}}>No previous sessions.</div>}
          {!sessionsLoading && sessions.map(s => (
            <div key={s.id} className={`session-row ${sessionId===s.id? 'active':''}`}>
              <div className="session-meta" onClick={()=>switchToSession(s.id)}>
                {renamingId === s.id ? (
                  <input
                    autoFocus
                    className="rename-input"
                    value={renameValue}
                    onChange={e=>setRenameValue(e.target.value)}
                    onKeyDown={e=>{ if(e.key==='Enter') submitRename(s); if(e.key==='Escape') setRenamingId(null); }}
                    onBlur={()=>submitRename(s)}
                    maxLength={120}
                  />
                ) : (
                  <>
                    <div className="title-line">{s.title || s.major_issue || ('Session ' + s.id.slice(0,6))}</div>
                    <div className="sub-line">{s.message_count || 0} msgs {s.analyzed_at? '• analyzed':''}</div>
                  </>
                )}
              </div>
              {renamingId === s.id ? (
                <button className="icon-btn save" title="Save" onClick={()=>submitRename(s)}>💾</button>
              ) : (
                <button className="icon-btn" title="Rename" onClick={()=>beginRename(s)}>✏️</button>
              )}
            </div>
          ))}
        </div>
      )}
      <div className="chat-window enhanced">
        {messages.map((m,i) => {
          const prev = messages[i-1];
            const grouped = prev && prev.role === m.role;
            const key = m.id || `${m.ts || ''}-${i}`; // ensure uniqueness
            if (m.role === 'bot' && typeof m.text === 'string' && looksLikeHtml(m.text)) {
              const safe = sanitizeHtml(m.text);
              return <div key={key} className={`bubble ${m.role} ${grouped? 'grouped':''}`} dangerouslySetInnerHTML={{__html: safe}} />;
            }
            const content = pendingMeta?.evidence ? highlightedText(m.text) : m.text;
            return <div key={key} className={`bubble ${m.role} ${grouped? 'grouped':''}`}>{content}</div>;
        })}
        {loading && <div className="bubble bot loading">Thinking...</div>}
        {loadingSessionSwitch && <div className="bubble bot loading">Loading session…</div>}
        <div ref={bottomRef} />
      </div>
      <form onSubmit={send} className="chat-input-row fancy">
        <input
          value={input}
            onChange={e=>setInput(e.target.value)}
            placeholder="Describe your symptom or ask a question..."
            onKeyDown={e=> { if (e.key==='Enter' && !e.shiftKey) { send(e); } }}
        />
        <button className="primary" disabled={loading}>{loading? '...' : 'Send'}</button>
        <button type="button" className="secondary" disabled={analyzing || messages.length===0} onClick={analyzeSession}>{analyzing? 'Analyzing...' : 'Analyze'}</button>
        {role==='patient' && !consultRequestId && (
          <button type="button" className="secondary" disabled={consultLoading || messages.length===0} onClick={escalateToDoctor}>{consultLoading? '...' : 'Contact Doctor'}</button>
        )}
      </form>
      {consultRequestId && <div className="alert info" style={{marginTop:6}}>Consult request submitted. ID: {consultRequestId.slice(0,8)}… Waiting for a doctor to accept.</div>}
      {consultRequestId && consultStatus==='accepted' && (
        <div className="consult-chat" style={{marginTop:12,display:'flex',flexDirection:'column',gap:8}}>
          <div className="alert success" style={{margin:0}}>Doctor connected. You can chat below.</div>
          <div className="chat-window enhanced" style={{minHeight:220}}>
            {consultMessages.map(m => (
              <div key={m.id} className={`bubble ${m.role==='patient' ? 'user':'bot'}`}>{m.text}</div>
            ))}
          </div>
          <div className="attachment-panel" style={{display:'flex',flexDirection:'column',gap:4}}>
            <div className="row" style={{gap:8,alignItems:'center'}}>
              <input type="file" onChange={e=> setAttachmentFile(e.target.files?.[0] || null)} accept=".pdf,.png,.jpg,.jpeg,.txt" />
              <button type="button" className="secondary" disabled={!attachmentFile || uploadingAttachment} onClick={uploadAttachment}>{uploadingAttachment? 'Uploading...' : 'Upload'}</button>
            </div>
            {attachments.length>0 && (
              <div className="attachments-list" style={{display:'flex',flexWrap:'wrap',gap:6}}>
                {attachments.map(f => (
                  <button type="button" key={f.filename} className="chip" style={{fontSize:'.55rem'}} onClick={()=>downloadAttachment(f)}>📎 {f.filename} ({Math.round(f.size/1024)}kB)</button>
                ))}
              </div>
            )}
          </div>
          <div className="chat-input-row" style={{marginTop:4}}>
            <input value={consultMsgInput} onChange={e=>setConsultMsgInput(e.target.value)} placeholder="Type a message to doctor" onKeyDown={e=>{ if(e.key==='Enter'){ sendConsultMessage(); } }} />
            <button type="button" className="primary" onClick={sendConsultMessage} disabled={!consultMsgInput.trim()}>Send</button>
          </div>
        </div>
      )}
      {pendingIssue && (
        <div className="alert info" style={{marginTop:8,display:'flex',flexDirection:'column',gap:6}}>
          <strong>Detected Issue (Pending): {pendingIssue}</strong>
          {pendingMeta?.confidence!=null && <span>Confidence: {(pendingMeta.confidence*100).toFixed(1)}%</span>}
          {pendingMeta?.evidence && pendingMeta.evidence.length>0 && <div className="evidence-row">Evidence: {pendingMeta.evidence.slice(0,8).join(', ')}</div>}
          <div className="row" style={{gap:8}}>
            <button type="button" className="primary" onClick={confirmSave}>Confirm & Save</button>
            <button type="button" className="ghost" onClick={cancelPending}>Dismiss</button>
          </div>
        </div>
      )}
      {sessionIssue && (
        <div className="alert success" style={{marginTop:8,display:'flex',flexDirection:'column',gap:4}}>
          <strong>Saved Issue: {sessionIssue}</strong>
          {sessionConfidence!=null && <span>Confidence: {(sessionConfidence*100).toFixed(1)}%</span>}
          {sessionEvidence.length>0 && <div>Evidence: {sessionEvidence.slice(0,10).join(', ')}</div>}
          <div>
            <button type="button" className="ghost" onClick={()=>onNavigateHistory && onNavigateHistory()}>View History ↗</button>
          </div>
        </div>
      )}
      <p className="hint">AI session heuristic can extract a dominant symptom and auto-store it. This is not a diagnosis.</p>
    </div>
  );
}
