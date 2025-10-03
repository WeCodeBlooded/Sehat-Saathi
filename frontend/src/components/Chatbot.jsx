import React, { useState, useEffect } from 'react';
import ChatWindow from './ChatWindow';
import MessageInput from './MessageInput';
import './Chatbot.css';

// IMPORTANT: Make sure this URL matches your backend's address
const API_URL = 'https://1d897642e66b.ngrok-free.app';

export default function Chatbot() {
  const [messages, setMessages] = useState([]);
  const [isTyping, setIsTyping] = useState(false);

  // This function now handles all user input and calls the backend API
  const handleUserInput = async (text) => {
    // Add the user's message to the UI immediately for a responsive feel
    const newUserMessage = { id: Date.now(), text, sender: 'user', read: false };
    setMessages(prev => [...prev, newUserMessage]);
    
    // Show the "typing..." indicator
    setIsTyping(true);
    
    const uid = localStorage.getItem('user_uid');

    try {
      // Call your backend /chat endpoint
      const response = await fetch(`${API_URL}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ uid: uid, message: text }),
      });
      
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.message || "Something went wrong on the server.");
      }
      
      // Create the bot's message from the API response
      const botMessage = { 
        id: Date.now() + 1, 
        text: data.reply, // Assuming your API returns a 'reply' field
        sender: 'bot', 
        options: data.options || [] // Assuming your API might return options
      };

      setMessages(prev => [...prev, botMessage]);

    } catch (error) {
      console.error("Failed to get chat response:", error);
      // Display an error message in the chat if the API call fails
      const errorMessage = {
        id: Date.now() + 1,
        text: "Sorry, I'm having trouble connecting right now. Please try again later.",
        sender: 'bot',
        options: []
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      // Hide the typing indicator
      setIsTyping(false);

      // Mark the user's message as "read"
      setTimeout(() => {
        setMessages(prev => prev.map(msg => 
          msg.id === newUserMessage.id ? { ...msg, read: true } : msg
        ));
      }, 500);
    }
  };

  // This hook sends the initial welcome message when the component loads
  useEffect(() => {
    // This first message can remain hardcoded or you could make it a special API call
    setMessages([{
      id: Date.now(),
      text: "Namaste! I am your AI Health Assistant. How can I help you today?",
      sender: 'bot',
      options: ["Check Symptoms", "Book an Appointment"]
    }]);
  }, []);


  return (
    <div className="chat-container">
      <ChatWindow messages={messages} isTyping={isTyping} onOptionClick={handleUserInput} />
      <MessageInput onSendMessage={handleUserInput} />
    </div>
  );
}