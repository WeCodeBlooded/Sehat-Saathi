import React, { useState, useRef } from 'react';
import './MessageInput.css';

function MessageInput({ onSendMessage }) {
  const [inputValue, setInputValue] = useState('');
  const [files, setFiles] = useState([]);
  const fileRef = useRef(null);

  const handleSend = () => {
    if (!inputValue.trim() && files.length === 0) return;
    const payload = files.length > 0 ? { text: inputValue.trim(), files } : inputValue.trim();
    onSendMessage(payload);
    setInputValue('');
    setFiles([]);
    // revoke object URLs if any
    files.forEach(f => { try { URL.revokeObjectURL(f.preview); } catch (e) {} });
  };

  const handleKeyPress = (e) => { if (e.key === 'Enter') handleSend(); };

  const handleFiles = (e) => {
    const selected = Array.from(e.target.files || []);
    // create preview urls
    const withPreview = selected.map(f => ({ file: f, preview: URL.createObjectURL(f), name: f.name, type: f.type }));
    setFiles(withPreview);
  };

  return (
    <div className="chat-input-area">
      <input
        type="text"
        value={inputValue}
        onChange={(e) => setInputValue(e.target.value)}
        onKeyPress={handleKeyPress}
        placeholder="Type a message..."
      />
      <input ref={fileRef} type="file" accept="image/*,video/*" multiple style={{ display: 'none' }} onChange={handleFiles} />
      <button className="mic-button" onClick={() => fileRef.current && fileRef.current.click()} title="Attach files"><i className="fa-solid fa-paperclip"></i></button>
      <button className="send-button" onClick={handleSend} title="Send">
        <i className="fa-solid fa-paper-plane"></i>
      </button>

      {/* previews */}
      {files.length > 0 && (
        <div className="attachment-previews">
          {files.map((f, i) => (
            <div key={i} className="preview-item">
              {f.type.startsWith('image') ? <img src={f.preview} alt={f.name} /> : <video src={f.preview} />}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default MessageInput;