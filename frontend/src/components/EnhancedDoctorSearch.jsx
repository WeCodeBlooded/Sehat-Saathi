import React, { useState, useEffect } from 'react';

export default function EnhancedDoctorSearch({ backend, uid }) {
  const [specialty, setSpecialty] = useState('');
  const [location, setLocation] = useState('');
  const [doctors, setDoctors] = useState([]);
  const [loading, setLoading] = useState(false);
  const [filters, setFilters] = useState({
    min_experience: 0,
    min_rating: 0,
    consultation_type: 'online',
    max_fee: 5000
  });
  const [error, setError] = useState('');
  const [selectedDoctor, setSelectedDoctor] = useState(null);
  const [showBooking, setShowBooking] = useState(false);

  const SPECIALTIES = [
    'cardiology', 'dermatology', 'neurology', 'orthopedics', 
    'pediatrics', 'psychiatry', 'gynecology', 'ophthalmology',
    'ent', 'gastroenterology', 'pulmonology', 'nephrology'
  ];

  const searchDoctors = async (e) => {
    e?.preventDefault();
    if (!specialty || !location) {
      setError('Please select specialty and location');
      return;
    }

    setLoading(true);
    setError('');
    
    try {
      const response = await fetch(`${backend}/search_external_doctors`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          specialty,
          location,
          filters
        })
      });

      const data = await response.json();
      if (response.ok) {
        setDoctors(data.doctors || []);
      } else {
        setError(data.error || 'Search failed');
      }
    } catch (err) {
      setError('Network error occurred');
    } finally {
      setLoading(false);
    }
  };

  const bookAppointment = (doctor) => {
    setSelectedDoctor(doctor);
    setShowBooking(true);
  };

  return (
    <div className="feature-card enhanced-doctor-search">
      <h2>Find Doctors</h2>
      <p className="subtitle">Search from verified doctors across platforms</p>

      {/* Search Form */}
      <form onSubmit={searchDoctors} className="search-form">
        <div className="form-grid">
          <label>
            Specialty *
            <select value={specialty} onChange={(e) => setSpecialty(e.target.value)}>
              <option value="">Select Specialty</option>
              {SPECIALTIES.map(spec => (
                <option key={spec} value={spec}>
                  {spec.charAt(0).toUpperCase() + spec.slice(1)}
                </option>
              ))}
            </select>
          </label>

          <label>
            Location *
            <input 
              value={location} 
              onChange={(e) => setLocation(e.target.value)}
              placeholder="City or Area"
            />
          </label>

          <label>
            Min Experience (years)
            <input 
              type="number" 
              value={filters.min_experience} 
              onChange={(e) => setFilters({...filters, min_experience: parseInt(e.target.value) || 0})}
              min="0"
            />
          </label>

          <label>
            Max Fee (₹)
            <input 
              type="number" 
              value={filters.max_fee} 
              onChange={(e) => setFilters({...filters, max_fee: parseInt(e.target.value) || 5000})}
              min="0"
            />
          </label>
        </div>

        <div className="form-options">
          <label>
            Consultation Type
            <select 
              value={filters.consultation_type} 
              onChange={(e) => setFilters({...filters, consultation_type: e.target.value})}
            >
              <option value="online">Online/Video</option>
              <option value="clinic">In-Clinic</option>
              <option value="both">Both</option>
            </select>
          </label>

          <label>
            Min Rating
            <select 
              value={filters.min_rating} 
              onChange={(e) => setFilters({...filters, min_rating: parseFloat(e.target.value)})}
            >
              <option value="0">Any Rating</option>
              <option value="3">3+ Stars</option>
              <option value="4">4+ Stars</option>
              <option value="4.5">4.5+ Stars</option>
            </select>
          </label>
        </div>

        <button type="submit" disabled={loading || !specialty || !location}>
          {loading ? 'Searching...' : 'Search Doctors'}
        </button>
      </form>

      {error && <div className="alert error">{error}</div>}

      {/* Results */}
      <div className="doctors-results">
        {loading && (
          <div className="loading-grid">
            {Array(6).fill(0).map((_, i) => (
              <div key={i} className="doctor-card skeleton" />
            ))}
          </div>
        )}

        {!loading && doctors.length === 0 && specialty && (
          <div className="empty-state">
            <p>No doctors found. Try adjusting your filters.</p>
          </div>
        )}

        {doctors.map((doctor, index) => (
          <div key={`${doctor.id || index}-${doctor.name}`} className={`doctor-card ${doctor.source}`}>
            <div className="doctor-header">
              <div className="doctor-avatar">
                {doctor.profile_image ? (
                  <img src={doctor.profile_image} alt={doctor.name} />
                ) : (
                  <div className="avatar-placeholder">
                    {doctor.name?.charAt(0) || 'D'}
                  </div>
                )}
              </div>
              
              <div className="doctor-info">
                <h3>{doctor.name}</h3>
                <p className="specialty">{doctor.specialty}</p>
                <div className="credentials">
                  {doctor.experience_years > 0 && (
                    <span className="experience">{doctor.experience_years} years exp</span>
                  )}
                  <span className="rating">
                    ⭐ {doctor.rating?.toFixed(1) || 'N/A'}
                    {doctor.total_reviews && ` (${doctor.total_reviews})`}
                  </span>
                </div>
              </div>

              <div className="doctor-actions">
                <span className="fee">₹{doctor.consultation_fee || 'N/A'}</span>
                <span className={`source-badge ${doctor.source}`}>
                  {doctor.source === 'lybrate' ? 'Lybrate' : 
                   doctor.source === 'practo' ? 'Practo' : 'Local'}
                </span>
              </div>
            </div>

            <div className="doctor-details">
              {doctor.qualifications?.length > 0 && (
                <p><strong>Qualifications:</strong> {doctor.qualifications.join(', ')}</p>
              )}
              {doctor.languages?.length > 0 && (
                <p><strong>Languages:</strong> {doctor.languages.join(', ')}</p>
              )}
              {doctor.clinic_name && (
                <p><strong>Clinic:</strong> {doctor.clinic_name}</p>
              )}
              {doctor.bio && (
                <p className="bio">{doctor.bio}</p>
              )}
            </div>

            <div className="available-modes">
              {doctor.available_modes?.includes('video') && (
                <span className="mode-badge video">📹 Video</span>
              )}
              {doctor.available_modes?.includes('chat') && (
                <span className="mode-badge chat">💬 Chat</span>
              )}
              {doctor.clinic_name && (
                <span className="mode-badge clinic">🏥 Clinic</span>
              )}
            </div>

            <div className="booking-actions">
              {doctor.next_available && (
                <p className="next-slot">Next available: {doctor.next_available}</p>
              )}
              
              <button 
                className="book-btn primary"
                onClick={() => bookAppointment(doctor)}
                disabled={doctor.source === 'local'}
              >
                {doctor.source === 'local' ? 'Contact Directly' : 'Book Appointment'}
              </button>
              
              {doctor.practo_profile_url && (
                <a 
                  href={doctor.practo_profile_url} 
                  target="_blank" 
                  rel="noopener noreferrer"
                  className="profile-link"
                >
                  View Profile ↗
                </a>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Booking Modal */}
      {showBooking && selectedDoctor && (
        <AppointmentBookingModal
          doctor={selectedDoctor}
          backend={backend}
          uid={uid}
          onClose={() => {setShowBooking(false); setSelectedDoctor(null);}}
        />
      )}
    </div>
  );
}

// Appointment Booking Modal Component
function AppointmentBookingModal({ doctor, backend, uid, onClose }) {
  const [patientInfo, setPatientInfo] = useState({
    name: '',
    phone: '',
    email: '',
    age: '',
    gender: 'male'
  });
  const [appointmentDetails, setAppointmentDetails] = useState({
    date: '',
    time: '',
    symptoms: '',
    consultation_mode: 'video'
  });
  const [booking, setBooking] = useState(false);
  const [bookingResult, setBookingResult] = useState(null);

  const handleBooking = async (e) => {
    e.preventDefault();
    setBooking(true);
    
    try {
      const response = await fetch(`${backend}/book_external_appointment`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          doctor_id: doctor.id,
          platform: doctor.source,
          patient_info: { ...patientInfo, uid },
          appointment_details: appointmentDetails
        })
      });

      const result = await response.json();
      setBookingResult(result);
      
      if (result.success) {
        // Auto-close after 3 seconds on success
        setTimeout(() => onClose(), 3000);
      }
    } catch (err) {
      setBookingResult({ success: false, error: 'Network error' });
    } finally {
      setBooking(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Book Appointment with {doctor.name}</h3>
          <button className="close-btn" onClick={onClose}>×</button>
        </div>

        {bookingResult ? (
          <div className={`booking-result ${bookingResult.success ? 'success' : 'error'}`}>
            {bookingResult.success ? (
              <div>
                <h4>✅ Booking Confirmed!</h4>
                <p><strong>Booking ID:</strong> {bookingResult.booking_id || bookingResult.appointment_id}</p>
                {bookingResult.meeting_link && (
                  <p><strong>Meeting Link:</strong> <a href={bookingResult.meeting_link} target="_blank" rel="noopener noreferrer">Join Call</a></p>
                )}
                {bookingResult.payment_link && (
                  <p><strong>Payment:</strong> <a href={bookingResult.payment_link} target="_blank" rel="noopener noreferrer">Complete Payment</a></p>
                )}
                <p><em>Closing in 3 seconds...</em></p>
              </div>
            ) : (
              <div>
                <h4>❌ Booking Failed</h4>
                <p>{bookingResult.error}</p>
                <button onClick={() => setBookingResult(null)}>Try Again</button>
              </div>
            )}
          </div>
        ) : (
          <form onSubmit={handleBooking} className="booking-form">
            <div className="form-section">
              <h4>Patient Information</h4>
              <div className="form-grid">
                <input
                  type="text"
                  placeholder="Full Name *"
                  value={patientInfo.name}
                  onChange={(e) => setPatientInfo({...patientInfo, name: e.target.value})}
                  required
                />
                <input
                  type="tel"
                  placeholder="Phone Number *"
                  value={patientInfo.phone}
                  onChange={(e) => setPatientInfo({...patientInfo, phone: e.target.value})}
                  required
                />
                <input
                  type="email"
                  placeholder="Email Address *"
                  value={patientInfo.email}
                  onChange={(e) => setPatientInfo({...patientInfo, email: e.target.value})}
                  required
                />
                <input
                  type="number"
                  placeholder="Age *"
                  value={patientInfo.age}
                  onChange={(e) => setPatientInfo({...patientInfo, age: e.target.value})}
                  required
                />
                <select
                  value={patientInfo.gender}
                  onChange={(e) => setPatientInfo({...patientInfo, gender: e.target.value})}
                >
                  <option value="male">Male</option>
                  <option value="female">Female</option>
                  <option value="other">Other</option>
                </select>
              </div>
            </div>

            <div className="form-section">
              <h4>Appointment Details</h4>
              <div className="form-grid">
                <input
                  type="date"
                  value={appointmentDetails.date}
                  onChange={(e) => setAppointmentDetails({...appointmentDetails, date: e.target.value})}
                  min={new Date().toISOString().split('T')[0]}
                  required
                />
                <input
                  type="time"
                  value={appointmentDetails.time}
                  onChange={(e) => setAppointmentDetails({...appointmentDetails, time: e.target.value})}
                  required
                />
                <select
                  value={appointmentDetails.consultation_mode}
                  onChange={(e) => setAppointmentDetails({...appointmentDetails, consultation_mode: e.target.value})}
                >
                  <option value="video">Video Call</option>
                  <option value="phone">Phone Call</option>
                  <option value="chat">Chat</option>
                </select>
              </div>
              <textarea
                placeholder="Describe your symptoms or reason for consultation"
                value={appointmentDetails.symptoms}
                onChange={(e) => setAppointmentDetails({...appointmentDetails, symptoms: e.target.value})}
                rows="3"
              />
            </div>

            <div className="booking-summary">
              <p><strong>Doctor:</strong> {doctor.name}</p>
              <p><strong>Specialty:</strong> {doctor.specialty}</p>
              <p><strong>Fee:</strong> ₹{doctor.consultation_fee}</p>
              <p><strong>Platform:</strong> {doctor.source}</p>
            </div>

            <div className="modal-actions">
              <button type="button" onClick={onClose} className="secondary">Cancel</button>
              <button type="submit" disabled={booking} className="primary">
                {booking ? 'Booking...' : 'Confirm Booking'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}