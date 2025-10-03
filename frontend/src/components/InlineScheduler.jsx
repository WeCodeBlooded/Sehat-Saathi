import React, { useState } from 'react';
import './InlineScheduler.css';

// Helper function to get the next few days
const getNextSevenDays = () => {
  const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const dates = [];
  for (let i = 0; i < 7; i++) {
    const date = new Date();
    date.setDate(date.getDate() + i);
    dates.push({
      dayName: days[date.getDay()],
      dateNum: date.getDate(),
      fullDate: date.toISOString().split('T')[0]
    });
  }
  return dates;
};

const availableTimeSlots = ["10:00 AM", "11:00 AM", "02:00 PM", "03:00 PM"];

export default function InlineScheduler({ onSchedule, onCancel }) {
  const [selectedDate, setSelectedDate] = useState(null);
  const [selectedTime, setSelectedTime] = useState(null);

  const handleConfirm = () => {
    if (selectedDate && selectedTime) {
      onSchedule(`Appointment confirmed for ${selectedDate.fullDate} at ${selectedTime}`);
    }
  };

  return (
    <div className="inline-scheduler">
      <p className="scheduler-subtitle">Select a Date</p>
      <div className="date-selector">
        {getNextSevenDays().map(day => (
          <div 
            key={day.fullDate}
            className={`date-chip ${selectedDate?.fullDate === day.fullDate ? 'selected' : ''}`}
            onClick={() => setSelectedDate(day)}
          >
            <span className="day-name">{day.dayName}</span>
            <span className="date-num">{day.dateNum}</span>
          </div>
        ))}
      </div>

      {selectedDate && (
        <>
          <p className="scheduler-subtitle">Select a Time</p>
          <div className="time-selector">
            {availableTimeSlots.map(time => (
              <div 
                key={time}
                className={`time-chip ${selectedTime === time ? 'selected' : ''}`}
                onClick={() => setSelectedTime(time)}
              >
                {time}
              </div>
            ))}
          </div>
        </>
      )}

      <div className="scheduler-buttons">
        <button 
          className="cancel-button" 
          onClick={() => onCancel("Cancel Booking")}
        >
          Cancel
        </button>
        <button 
          className="confirm-button" 
          onClick={handleConfirm}
          disabled={!selectedDate || !selectedTime}
        >
          Confirm
        </button>
      </div>
    </div>
  );
}