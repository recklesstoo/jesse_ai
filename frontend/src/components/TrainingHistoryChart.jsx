import React, { useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

const TrainingHistoryChart = ({ botId = 'bot-1' }) => {
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);

  const fetchHistory = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/ml/history/${botId}`);
      if (res.ok) {
        const data = await res.json();
        setHistory(data.history || []);
      }
    } catch (err) {
      console.error("Failed to fetch training history", err);
    } finally {
      setLoading(false);
    }
  };

  const handleClearHistory = async () => {
    if (!confirm("¿Estás seguro de borrar todo el historial de entrenamiento?")) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/ml/history/${botId}`, {
        method: "DELETE"
      });
      if (res.ok) {
        setHistory([]);
      }
    } catch (err) {
      console.error("Failed to clear history", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchHistory();
  }, [botId]);

  if (loading && history.length === 0) return <div className="text-xs text-gray-500 p-4">Cargando historial...</div>;
  if (!history.length) return null;

  // Lógica simple para gráfico SVG
  // X: índice, Y: valor (0-1)
  const width = 100;
  const height = 100;
  
  const getPoints = (key) => {
    return history.map((entry, idx) => {
      const val = Number(entry[key]) || 0;
      const x = (idx / (Math.max(history.length - 1, 1))) * width;
      const y = height - (val * height); // Invertir Y para SVG (0 es arriba)
      return `${x},${y}`;
    }).join(" ");
  };

  const pointsAcc = getPoints('accuracy');
  const pointsF1 = getPoints('f1');
  const pointsPrec = getPoints('precision');

  const lastEntry = history[history.length - 1];

  return (
    <div className="p-4 bg-gray-800 rounded-lg border border-gray-700 text-white shadow-md mt-4">
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-bold text-blue-400 flex items-center gap-2">
          📈 Evolución del Modelo
        </h3>
        <div className="flex gap-2">
          <button 
            onClick={handleClearHistory} 
            className="text-xs bg-red-900/30 hover:bg-red-800 text-red-200 px-2 py-1 rounded border border-red-800 transition-colors"
          >
            Borrar
          </button>
          <button 
            onClick={fetchHistory} 
            className="text-xs bg-gray-700 hover:bg-gray-600 px-2 py-1 rounded border border-gray-600 transition-colors"
          >
            Refrescar
          </button>
        </div>
      </div>
      
      <div className="relative h-40 w-full bg-gray-900/50 rounded border border-gray-700 overflow-hidden p-2">
        <svg className="w-full h-full overflow-visible" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
          {/* Grid lines */}
          {[0, 25, 50, 75, 100].map(y => (
            <line key={y} x1="0" y1={y} x2="100" y2={y} stroke="#374151" strokeWidth="0.5" strokeDasharray="2" />
          ))}
          
          {/* Trend Line Accuracy */}
          <polyline
            fill="none"
            stroke="#3b82f6" // Blue
            strokeWidth="2"
            points={pointsAcc}
            vectorEffect="non-scaling-stroke"
          />

          {/* Trend Line F1 */}
          <polyline
            fill="none"
            stroke="#10b981" // Green
            strokeWidth="2"
            points={pointsF1}
            vectorEffect="non-scaling-stroke"
            strokeDasharray="4"
          />

          {/* Trend Line Precision */}
          <polyline
            fill="none"
            stroke="#f59e0b" // Amber/Orange
            strokeWidth="2"
            points={pointsPrec}
            vectorEffect="non-scaling-stroke"
            strokeDasharray="2"
          />
        </svg>
        
        {/* Labels overlay */}
        <div className="absolute top-0 left-1 text-[10px] text-gray-500">100%</div>
        <div className="absolute top-1/4 left-1 text-[10px] text-gray-500">75%</div>
        <div className="absolute top-1/2 left-1 text-[10px] text-gray-500">50%</div>
        <div className="absolute top-3/4 left-1 text-[10px] text-gray-500">25%</div>
        <div className="absolute bottom-0 left-1 text-[10px] text-gray-500">0%</div>
      </div>

      <div className="mt-2 text-xs font-mono flex justify-between items-center">
        <span className="text-gray-400">Inicio: {new Date(history[0].ts).toLocaleDateString()}</span>
        <div className="flex gap-3">
          <span className="text-blue-400 flex items-center gap-1">
            <span className="w-2 h-2 bg-blue-500 rounded-full inline-block"></span>
            Acc: {(lastEntry.accuracy * 100).toFixed(1)}%
          </span>
          <span className="text-green-400 flex items-center gap-1">
            <span className="w-2 h-2 bg-green-500 rounded-full inline-block"></span>
            F1: {(lastEntry.f1 * 100).toFixed(1)}%
          </span>
          <span className="text-yellow-400 flex items-center gap-1">
            <span className="w-2 h-2 bg-yellow-500 rounded-full inline-block"></span>
            Prec: {(Number(lastEntry.precision || 0) * 100).toFixed(1)}%
          </span>
        </div>
      </div>
    </div>
  );
};

export default TrainingHistoryChart;