import React, { useState, useEffect, useRef } from 'react';
import './History.css';

// IMPORTANT: Make sure this URL matches your backend's address
const API_URL = 'https://1d897642e66b.ngrok-free.app';

export default function History() {
  const [records, setRecords] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  
  // State for the new record form
  const [newSymptom, setNewSymptom] = useState('');
  const [newNotes, setNewNotes] = useState('');
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [previews, setPreviews] = useState([]);
  const fileInputRef = useRef(null);

  // Function to fetch health history from the backend
  const fetchHistory = async () => {
    setIsLoading(true);
    const uid = localStorage.getItem('user_uid');
    if (!uid) {
      setIsLoading(false);
      // In a real app, you might show an error here
      return;
    }
    try {
      const response = await fetch(`${API_URL}/get_health_history`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ uid }),
      });
      const data = await response.json();
      if (response.ok) {
        // Assuming the backend returns an object with a 'history' array
        setRecords(data.history || []);
      } else {
        throw new Error(data.message || "Failed to fetch history");
      }
    } catch (error) {
      console.error("Failed to fetch history:", error);
    } finally {
      setIsLoading(false);
    }
  };

  // Fetch history when the component first loads
  useEffect(() => {
    fetchHistory();
  }, []);

  // Function to handle submitting the new record form
  const handleAddRecord = async (e) => {
    e.preventDefault();
    const uid = localStorage.getItem('user_uid');
    const newRecord = {
      date: new Date().toISOString().split('T')[0], // Use today's date
      symptom: newSymptom,
      notes: newNotes,
    };

    try {
      // Support uploading files (images/videos). Use FormData for files.
      const form = new FormData();
      form.append('uid', uid);
      form.append('record', JSON.stringify(newRecord));
      if (selectedFiles && selectedFiles.length > 0) {
        selectedFiles.forEach((f, idx) => {
          // backend should accept multiple files under 'files' key
          form.append('files', f, f.name || `file_${idx}`);
        });
      }

      const response = await fetch(`${API_URL}/add_health_record`, {
        method: 'POST',
        body: form,
      });

      if (response.ok) {
        setShowModal(false); // Close the modal on success
        setNewSymptom('');   // Reset form fields
        setNewNotes('');
        setSelectedFiles([]);
        setPreviews([]);
        fetchHistory();      // Refresh the list with the new record
      } else {
        const data = await response.json();
        throw new Error(data.message || "Failed to add record");
      }
    } catch (error) {
      console.error("Failed to add record:", error);
      // You could show an error message to the user here
    }
  };

  // handle file selection and build previews
  const handleFilesChange = (e) => {
    const files = Array.from(e.target.files || []);
    setSelectedFiles(files);
    const p = files.map(f => ({
      url: URL.createObjectURL(f),
      type: f.type,
      name: f.name,
    }));
    setPreviews(p);
  };

  const removeSelectedFile = (idx) => {
    setSelectedFiles(prev => prev.filter((_, i) => i !== idx));
    setPreviews(prev => {
      const removed = prev[idx];
      try { URL.revokeObjectURL(removed.url); } catch (e) {}
      return prev.filter((_, i) => i !== idx);
    });
  };

  return (
    <div className="history-container">
      <div className="history-header">
        <h2>Health History</h2>
        <p>A timeline of your past consultations and records.</p>
      </div>

      {isLoading ? (
        <p>Loading your health history...</p>
      ) : records.length === 0 ? (
        <p>No health records found. Click the '+' button to add your first record.</p>
      ) : (
        <div className="timeline">
          {records.map((record, index) => (
            <div key={index} className="timeline-item">
              <div className="timeline-dot"></div>
              <div className="record-card">
                <span className="record-date">{record.date}</span>
                <h4 className="record-symptom">{record.symptom}</h4>
                <p className="record-notes">{record.notes}</p>
                {/* Render attached files if backend provides URLs in record.files */}
                {record.files && record.files.length > 0 && (
                  <div className="record-media" style={{ marginTop: 10, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                    {record.files.map((f, i) => (
                      <div key={i} style={{ width: 140, height: 100, overflow: 'hidden', borderRadius: 6, background: '#fafafa' }}>
                        {f.url && f.type && f.type.startsWith('image') ? (
                          <img src={f.url} alt={f.name || 'attachment'} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                        ) : f.url && f.type && f.type.startsWith('video') ? (
                          <video src={f.url} controls style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                        ) : null}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* "Add New Record" Floating Action Button */}
      <button className="add-record-button" onClick={() => setShowModal(true)}>
        <i className="fa-solid fa-plus"></i>
      </button>

      {/* The Modal for adding a new record */}
      {showModal && (
        <div className="modal-overlay">
          <div className="modal-content">
            <form onSubmit={handleAddRecord}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <h3 style={{ margin: 0 }}>Add New Health Record</h3>
                <button type="button" className="attach-btn" onClick={() => fileInputRef.current && fileInputRef.current.click()}>
                  Attach files
                </button>
              </div>
              <div className="input-group">
                <label>Symptom / Ailment</label>
                <input
                  type="text"
                  value={newSymptom}
                  onChange={(e) => setNewSymptom(e.target.value)}
                  placeholder="e.g., Fever and Cough"
                  required
                />
              </div>
              <div className="input-group">
                <label>Doctor's Notes / Prescription</label>
                <textarea
                  value={newNotes}
                  onChange={(e) => setNewNotes(e.target.value)}
                  placeholder="e.g., Paracetamol 500mg, twice a day"
                  rows="4"
                  required
                ></textarea>
              </div>

              <div className="input-group">
                <label>Attach images / videos (optional)</label>
                <input ref={fileInputRef} type="file" accept="image/*,video/*" multiple onChange={handleFilesChange} />
                {previews && previews.length > 0 && (
                  <div className="preview-row">
                    {previews.map((p, i) => (
                      <div className="preview-item" key={i}>
                        {p.type.startsWith('image') ? (
                          <img src={p.url} alt={p.name} />
                        ) : (
                          <video src={p.url} controls />
                        )}
                        <button type="button" className="remove-file" onClick={() => removeSelectedFile(i)}>Remove</button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div className="modal-buttons">
                <button type="button" className="cancel-btn" onClick={() => setShowModal(false)}>Cancel</button>
                <button type="submit" className="save-btn">Save Record</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
