import React, { useState, useEffect } from 'react';

export default function LabTestBooking({ backend, uid }) {
  const [location, setLocation] = useState('');
  const [category, setCategory] = useState('');
  const [homeCollection, setHomeCollection] = useState(true);
  const [labTests, setLabTests] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [cart, setCart] = useState([]);
  const [showCart, setShowCart] = useState(false);

  const categories = [
    { value: '', label: 'All Tests' },
    { value: 'blood', label: 'Blood Tests' },
    { value: 'urine', label: 'Urine Tests' },
    { value: 'cardiac', label: 'Heart Health' },
    { value: 'diabetes', label: 'Diabetes Panel' },
    { value: 'thyroid', label: 'Thyroid Function' },
    { value: 'liver', label: 'Liver Function' },
    { value: 'kidney', label: 'Kidney Function' },
    { value: 'vitamin', label: 'Vitamin Deficiency' },
    { value: 'infection', label: 'Infection Tests' },
    { value: 'cancer', label: 'Cancer Screening' }
  ];

  const searchLabTests = async (e) => {
    e?.preventDefault();
    if (!location.trim()) {
      setError('Please enter your location');
      return;
    }

    setLoading(true);
    setError('');

    try {
      const response = await fetch(`${backend}/get_lab_tests`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          location: location.trim(),
          category,
          home_collection: homeCollection
        })
      });

      const data = await response.json();
      if (response.ok) {
        setLabTests(data.lab_tests || []);
      } else {
        setError(data.error || 'Failed to fetch lab tests');
      }
    } catch (err) {
      setError('Network error occurred');
    } finally {
      setLoading(false);
    }
  };

  const addToCart = (test) => {
    setCart(prev => {
      const exists = prev.find(item => item.id === test.id);
      if (exists) return prev;
      return [...prev, { ...test, quantity: 1 }];
    });
  };

  const removeFromCart = (testId) => {
    setCart(prev => prev.filter(item => item.id !== testId));
  };

  const getTotalPrice = () => {
    return cart.reduce((total, item) => total + (item.discount_price || item.price || 0), 0);
  };

  const getOriginalPrice = () => {
    return cart.reduce((total, item) => total + (item.price || 0), 0);
  };

  const proceedToBooking = () => {
    // This would typically redirect to payment gateway
    alert('Booking functionality would integrate with payment gateway');
  };

  useEffect(() => {
    // Auto-search when location changes (with debounce)
    const timer = setTimeout(() => {
      if (location.trim()) {
        searchLabTests();
      }
    }, 500);
    return () => clearTimeout(timer);
  }, [location, category, homeCollection]);

  return (
    <div className="feature-card lab-test-booking">
      <div className="lab-header">
        <h2>Book Lab Tests</h2>
        <p className="subtitle">Get tested at home or at nearby labs</p>
        
        {cart.length > 0 && (
          <button 
            className="cart-toggle"
            onClick={() => setShowCart(!showCart)}
          >
            🛒 Cart ({cart.length}) - ₹{getTotalPrice()}
          </button>
        )}
      </div>

      {/* Search Form */}
      <form onSubmit={searchLabTests} className="search-form">
        <div className="form-grid">
          <label>
            Your Location *
            <input
              type="text"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder="Enter your city or area"
            />
          </label>

          <label>
            Test Category
            <select value={category} onChange={(e) => setCategory(e.target.value)}>
              {categories.map(cat => (
                <option key={cat.value} value={cat.value}>{cat.label}</option>
              ))}
            </select>
          </label>
        </div>

        <div className="form-options">
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={homeCollection}
              onChange={(e) => setHomeCollection(e.target.checked)}
            />
            <span>Home collection only</span>
          </label>
        </div>

        <button type="submit" disabled={loading || !location.trim()}>
          {loading ? 'Searching...' : 'Search Tests'}
        </button>
      </form>

      {error && <div className="alert error">{error}</div>}

      {/* Cart Sidebar */}
      {showCart && cart.length > 0 && (
        <div className="cart-sidebar">
          <div className="cart-header">
            <h3>Selected Tests ({cart.length})</h3>
            <button onClick={() => setShowCart(false)}>×</button>
          </div>
          
          <div className="cart-items">
            {cart.map(item => (
              <div key={item.id} className="cart-item">
                <div className="item-info">
                  <h4>{item.name}</h4>
                  <p className="category">{item.category}</p>
                </div>
                <div className="item-actions">
                  <span className="price">
                    {item.discount_price ? (
                      <>
                        <span className="discounted">₹{item.discount_price}</span>
                        <span className="original">₹{item.price}</span>
                      </>
                    ) : (
                      <span>₹{item.price}</span>
                    )}
                  </span>
                  <button onClick={() => removeFromCart(item.id)} className="remove-btn">
                    🗑️
                  </button>
                </div>
              </div>
            ))}
          </div>

          <div className="cart-summary">
            <div className="price-breakdown">
              <div className="line-item">
                <span>Original Price:</span>
                <span>₹{getOriginalPrice()}</span>
              </div>
              {getOriginalPrice() > getTotalPrice() && (
                <div className="line-item savings">
                  <span>You Save:</span>
                  <span>₹{getOriginalPrice() - getTotalPrice()}</span>
                </div>
              )}
              <div className="line-item total">
                <span><strong>Total:</strong></span>
                <span><strong>₹{getTotalPrice()}</strong></span>
              </div>
            </div>
            
            <button className="checkout-btn primary" onClick={proceedToBooking}>
              Proceed to Book
            </button>
          </div>
        </div>
      )}

      {/* Test Results */}
      <div className="lab-tests-results">
        {loading && (
          <div className="loading-grid">
            {Array(8).fill(0).map((_, i) => (
              <div key={i} className="test-card skeleton" />
            ))}
          </div>
        )}

        {!loading && labTests.length === 0 && location && (
          <div className="empty-state">
            <p>No lab tests found for your criteria. Try changing the category or location.</p>
          </div>
        )}

        <div className="tests-grid">
          {labTests.map(test => {
            const isInCart = cart.some(item => item.id === test.id);
            
            return (
              <div key={test.id} className={`test-card ${isInCart ? 'in-cart' : ''}`}>
                <div className="test-header">
                  <h3>{test.name}</h3>
                  <span className={`category-badge ${test.category}`}>
                    {test.category}
                  </span>
                </div>

                <div className="test-details">
                  {test.description && (
                    <p className="description">{test.description}</p>
                  )}
                  
                  <div className="test-info">
                    {test.sample_type && (
                      <span className="info-item">
                        🧪 {test.sample_type}
                      </span>
                    )}
                    
                    {test.reporting_time && (
                      <span className="info-item">
                        ⏱️ {test.reporting_time}
                      </span>
                    )}
                    
                    {test.fasting_required && (
                      <span className="info-item warning">
                        🚫 Fasting required
                      </span>
                    )}
                    
                    {test.home_collection && (
                      <span className="info-item success">
                        🏠 Home collection
                      </span>
                    )}
                  </div>

                  {test.preparation_instructions && (
                    <div className="preparation">
                      <strong>Preparation:</strong>
                      <p>{test.preparation_instructions}</p>
                    </div>
                  )}
                </div>

                <div className="test-footer">
                  <div className="pricing">
                    {test.discount_price ? (
                      <>
                        <span className="current-price">₹{test.discount_price}</span>
                        <span className="original-price">₹{test.price}</span>
                        <span className="discount">
                          {Math.round((1 - test.discount_price / test.price) * 100)}% OFF
                        </span>
                      </>
                    ) : (
                      <span className="current-price">₹{test.price || 'Price on request'}</span>
                    )}
                  </div>

                  <div className="test-actions">
                    {isInCart ? (
                      <button 
                        className="added-btn"
                        onClick={() => removeFromCart(test.id)}
                      >
                        ✓ Added - Remove
                      </button>
                    ) : (
                      <button 
                        className="add-btn primary"
                        onClick={() => addToCart(test)}
                      >
                        Add to Cart
                      </button>
                    )}
                  </div>
                </div>

                {test.lab_partners && test.lab_partners.length > 0 && (
                  <div className="lab-partners">
                    <small>Available at: {test.lab_partners.slice(0, 2).join(', ')}
                      {test.lab_partners.length > 2 && ` +${test.lab_partners.length - 2} more`}
                    </small>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Popular Tests Section */}
      {labTests.length === 0 && !loading && !location && (
        <div className="popular-tests">
          <h3>Popular Health Checkups</h3>
          <div className="popular-grid">
            {[
              { name: 'Complete Blood Count (CBC)', price: 300, category: 'blood' },
              { name: 'Lipid Profile', price: 400, category: 'cardiac' },
              { name: 'Thyroid Function Test', price: 600, category: 'thyroid' },
              { name: 'HbA1c (Diabetes)', price: 500, category: 'diabetes' },
              { name: 'Liver Function Test', price: 450, category: 'liver' },
              { name: 'Kidney Function Test', price: 400, category: 'kidney' }
            ].map((test, index) => (
              <div key={index} className="popular-test-card">
                <h4>{test.name}</h4>
                <span className="price">Starting from ₹{test.price}</span>
                <button 
                  className="quick-search"
                  onClick={() => {
                    setCategory(test.category);
                    if (location) searchLabTests();
                  }}
                >
                  Find Labs
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}