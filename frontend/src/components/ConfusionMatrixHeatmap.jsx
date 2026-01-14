import React, { useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

const ConfusionMatrixHeatmap = ({ botId = 'bot-1' }) => {
  const [matrix, setMatrix] = useState(null);
  const [loading, setLoading] = useState(false);
  const [limit, setLimit] = useState(0); // 0 = Todos

  const fetchMatrix = async () => {
    setLoading(true);
    try {
      let url = `${API_BASE}/api/v1/ml/confusion-matrix/${botId}`;
      if (limit > 0) url += `?limit=${limit}`;
      const res = await fetch(url);
      if (res.ok) {
        const data = await res.json();
        setMatrix(data.confusion_matrix);
      }
    } catch (err) {
      console.error("Failed to fetch confusion matrix", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchMatrix();
  }, [botId, limit]);

  if (loading && !matrix) return <div className="text-xs text-gray-500 p-4">Cargando matriz...</div>;
  if (!matrix) return null;

  // Aplanar para encontrar el valor máximo para escalar colores
  const flat = matrix.flat();
  const maxVal = Math.max(...flat, 1);

  return (
    <div className="p-4 bg-gray-800 rounded-lg border border-gray-700 text-white shadow-md mt-4">
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-bold text-blue-400 flex items-center gap-2">
          🔥 Matriz de Confusión (Histórica)
        </h3>
        <div className="flex gap-2">
          <select 
            value={limit} 
            onChange={(e) => setLimit(Number(e.target.value))}
            className="text-xs bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white outline-none"
          >
            <option value={0}>Todos</option>
            <option value={5}>Últimos 5</option>
            <option value={10}>Últimos 10</option>
          </select>
          <button 
            onClick={fetchMatrix} 
            className="text-xs bg-gray-700 hover:bg-gray-600 px-2 py-1 rounded border border-gray-600 transition-colors"
          >
            Refrescar
          </button>
        </div>
      </div>

      <div className="flex flex-col items-center py-2">
        {/* Contenedor con etiquetas de ejes */}
        <div className="relative p-2">
            {/* Etiqueta Eje Y */}
            <div className="absolute -left-4 top-1/2 -translate-y-1/2 -rotate-90 text-[10px] text-gray-400 font-mono tracking-widest whitespace-nowrap">
                REAL
            </div>
            
            {/* Etiqueta Eje X */}
            <div className="absolute -top-4 left-1/2 -translate-x-1/2 text-[10px] text-gray-400 font-mono tracking-widest whitespace-nowrap">
                PREDICCIÓN
            </div>

            <div className="grid gap-1" style={{ gridTemplateColumns: `repeat(${matrix.length}, minmax(0, 1fr))` }}>
            {matrix.map((row, i) => (
                row.map((val, j) => {
                // Calcular intensidad (0 a 1)
                const intensity = val / maxVal;
                // Escala azul: color base blue-500 (#3b82f6)
                // Usamos rgba para ajustar opacidad según intensidad
                const opacity = Math.max(intensity, 0.15);
                const bgColor = `rgba(59, 130, 246, ${opacity})`;
                
                return (
                    <div 
                    key={`${i}-${j}`} 
                    className="w-16 h-16 flex flex-col items-center justify-center border border-gray-600/50 rounded relative group transition-all hover:border-blue-400"
                    style={{ backgroundColor: bgColor }}
                    title={`Real: ${i}, Pred: ${j}`}
                    >
                    <span className="font-bold text-white drop-shadow-md text-sm">{val.toFixed(1)}</span>
                    <span className="text-[9px] text-gray-300 opacity-50 group-hover:opacity-100 absolute bottom-1">
                        {i === j ? (i === 1 ? 'TP' : 'TN') : (i === 0 ? 'FP' : 'FN')}
                    </span>
                    </div>
                );
                })
            ))}
            </div>
        </div>
        
        <div className="mt-2 text-[10px] text-gray-500 italic">
          {limit > 0 ? `Promedio de los últimos ${limit} entrenamientos.` : "Promedio de todas las sesiones de entrenamiento registradas."}
        </div>
      </div>
    </div>
  );
};

export default ConfusionMatrixHeatmap;