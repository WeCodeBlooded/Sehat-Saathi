import React from 'react';
import { useNavigate } from 'react-router-dom';
import './Dashboard.css'; // Import the new stylesheet

// This is our main Home Screen component
export default function Dashboard() {
  // useNavigate is a hook from react-router-dom to handle navigation
  const navigate = useNavigate();

  return (
    <div className="dashboard-container">
      <header className="welcome-header">
        <h2>Welcome Back, Aditya!</h2>
        <p>Your central hub for managing your health.</p>
      </header>

      {/* Grid for our main action cards */}
      <div className="action-grid">
        <div className="action-card" onClick={() => navigate('/chatbot')}>
          <i className="fa-solid fa-robot card-icon"></i>
          <h3>AI Chatbot</h3>
          <p>Get instant first-aid and health advice.</p>
        </div>

        <div className="action-card" onClick={() => navigate('/scheduler')}>
          <i className="fa-solid fa-calendar-check card-icon"></i>
          <h3>Appointments</h3>
          <p>Schedule a tele-counselling session.</p>
        </div>

        <div className="action-card" onClick={() => navigate('/locator')}>
          <i className="fa-solid fa-hospital card-icon"></i>
          <h3>Hospital Locator</h3>
          <p>Find nearby government hospitals.</p>
        </div>

        <div className="action-card" onClick={() => navigate('/history')}>
          <i className="fa-solid fa-notes-medical card-icon"></i>
          <h3>Health History</h3>
          <p>View your past consultations.</p>
        </div>
      </div>

      {/* A simple card for a daily tip */}
      <div className="health-tip-card">
        <h4>Health Tip of the Day</h4>
        <p>Remember to drink at least 8 glasses of water a day to stay hydrated.</p>
      </div>
    </div>
  );
}