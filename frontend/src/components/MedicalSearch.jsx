import React, { useState } from 'react';

const MedicalSearch = ({ backend, notify }) => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  const searchMedicalInfo = async (e) => {
    e.preventDefault();
    if (!query.trim()) return;
    
    setLoading(true);
    setSearched(true);
    
    try {
      const res = await fetch(`${backend}/search_medical_info`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: query.trim(), max_results: 5 })
      });
      
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Search failed');
      
      setResults(data.results || []);
      
      if (data.results && data.results.length === 0) {
        notify && notify('No medical information found for this query. Try different search terms.', 'info');
      }
      
    } catch (err) {
      notify && notify(`Search failed: ${err.message}`, 'error');
      setResults([]);
    } finally {
      setLoading(false);
    }
  };

  const clearSearch = () => {
    setQuery('');
    setResults([]);
    setSearched(false);
  };

  return (
    <div className="feature-card medical-search">
      <h2>🔍 Medical Information Search</h2>
      <p style={{ fontSize: '0.85rem', color: '#666', marginBottom: '12px' }}>
        Search authoritative medical information from NIH MedlinePlus
      </p>
      
      <form onSubmit={searchMedicalInfo} className="search-form">
        <div style={{ display: 'flex', gap: '8px', marginBottom: '12px' }}>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search for conditions, symptoms, treatments..."
            style={{ flex: 1, padding: '8px', borderRadius: '4px', border: '1px solid #ddd' }}
            disabled={loading}
          />
          <button 
            type="submit" 
            className="primary"
            disabled={loading || !query.trim()}
          >
            {loading ? '...' : 'Search'}
          </button>
          {searched && (
            <button 
              type="button" 
              className="ghost"
              onClick={clearSearch}
            >
              Clear
            </button>
          )}
        </div>
      </form>

      {loading && (
        <div className="loading-state" style={{ textAlign: 'center', padding: '20px' }}>
          <div style={{ fontSize: '0.9rem', color: '#666' }}>Searching MedlinePlus database...</div>
        </div>
      )}

      {searched && !loading && results.length === 0 && (
        <div className="empty-state" style={{ 
          textAlign: 'center', 
          padding: '20px', 
          backgroundColor: '#f9f9f9', 
          borderRadius: '8px',
          color: '#666'
        }}>
          <div>No results found for "{query}"</div>
          <div style={{ fontSize: '0.8rem', marginTop: '4px' }}>
            Try searching for common medical terms, conditions, or symptoms
          </div>
        </div>
      )}

      {results.length > 0 && (
        <div className="search-results">
          <div style={{ 
            fontSize: '0.85rem', 
            color: '#666', 
            marginBottom: '12px',
            padding: '8px',
            backgroundColor: 'rgba(33, 150, 243, 0.1)',
            borderRadius: '4px'
          }}>
            Found {results.length} result{results.length !== 1 ? 's' : ''} from MedlinePlus
          </div>
          
          {results.map((result, index) => (
            <div 
              key={index} 
              className="result-card"
              style={{
                border: '1px solid #e0e0e0',
                borderRadius: '8px',
                padding: '16px',
                marginBottom: '12px',
                backgroundColor: '#fff'
              }}
            >
              <h3 style={{ 
                margin: '0 0 8px 0', 
                fontSize: '1.1rem',
                color: '#2196F3'
              }}>
                {result.title}
              </h3>
              
              {result.summary && (
                <p style={{ 
                  margin: '8px 0',
                  fontSize: '0.9rem',
                  lineHeight: '1.5',
                  color: '#333'
                }}>
                  {result.summary.length > 300 
                    ? result.summary.substring(0, 300) + '...' 
                    : result.summary}
                </p>
              )}
              
              <div style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginTop: '12px',
                paddingTop: '8px',
                borderTop: '1px solid #f0f0f0'
              }}>
                <div style={{ fontSize: '0.75rem', color: '#666' }}>
                  Source: {result.organization || 'MedlinePlus'}
                </div>
                
                {result.url && (
                  <a
                    href={result.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="primary"
                    style={{
                      padding: '6px 12px',
                      fontSize: '0.8rem',
                      textDecoration: 'none',
                      borderRadius: '4px'
                    }}
                  >
                    Read Full Article →
                  </a>
                )}
              </div>
            </div>
          ))}
          
          <div style={{
            marginTop: '16px',
            padding: '12px',
            backgroundColor: '#fff3cd',
            borderRadius: '6px',
            fontSize: '0.8rem',
            color: '#856404'
          }}>
            <strong>Disclaimer:</strong> This information is for educational purposes only and should not replace professional medical advice, diagnosis, or treatment.
          </div>
        </div>
      )}
    </div>
  );
};

export default MedicalSearch;