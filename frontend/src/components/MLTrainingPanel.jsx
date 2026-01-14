import React, { useState } from 'react';

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

const MLTrainingPanel = ({ botId = 'bot-1', onToast }) => {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [nEstimators, setNEstimators] = useState(100);
  const [maxDepth, setMaxDepth] = useState(5);
  const [testSize, setTestSize] = useState(0.2);

  const handleDownload = async () => {
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/api/v1/ml/model/${botId}`);
      if (response.ok) {
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${botId}.joblib`;
        document.body.appendChild(a);
        a.click();
        a.remove();
      } else {
        const data = await response.json();
        const errMsg = data.error || 'No se pudo descargar el modelo.';
        setError(errMsg);
        if (onToast) onToast(errMsg, "error");
      }
    } catch (err) {
      setError('Error de conexión al descargar.');
      if (onToast) onToast('Error de conexión al descargar.', "error");
    }
  };

  const handleTrain = async () => {
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const response = await fetch(`${API_BASE}/api/v1/ml/train`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ 
          botId, 
          force: true,
          n_estimators: Number(nEstimators),
          max_depth: Number(maxDepth),
          test_size: Number(testSize)
        }),
      });

      const data = await response.json();

      if (data.trained) {
        setResult(data.details);
        if (onToast) onToast("Entrenamiento completado exitosamente", "success");
      } else {
        const errMsg = data.details?.error || 'El entrenamiento falló sin detalles.';
        setError(errMsg);
        if (onToast) onToast(errMsg, "error");
      }
    } catch (err) {
      setError(err.message || 'Error de conexión con el backend.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-4 bg-gray-800 rounded-lg border border-gray-700 text-white shadow-md">
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-bold text-blue-400 flex items-center gap-2">
          🧠 Entrenamiento ML
        </h3>
        <div className="flex gap-2">
          <button
            onClick={handleDownload}
            className="px-3 py-2 rounded font-bold text-xs bg-gray-700 hover:bg-gray-600 text-gray-200 border border-gray-600 transition-colors"
            title="Descargar modelo .joblib"
          >
            ⬇ Modelo
          </button>
          <button
            onClick={handleTrain}
            disabled={loading}
            className={`px-4 py-2 rounded font-bold text-sm transition-colors ${
              loading
                ? 'bg-gray-600 cursor-not-allowed text-gray-300'
                : 'bg-blue-600 hover:bg-blue-500 text-white'
            }`}
          >
            {loading ? 'Entrenando...' : 'Iniciar Entrenamiento'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4 mb-4 bg-gray-700/30 p-3 rounded border border-gray-600/50">
        <div>
          <label className="block text-xs text-gray-400 mb-1 uppercase tracking-wider">Trees (n_estimators)</label>
          <input 
            type="number" 
            value={nEstimators} 
            onChange={(e) => setNEstimators(e.target.value)}
            className="w-full bg-gray-900 border border-gray-600 rounded px-2 py-1 text-sm text-white focus:border-blue-500 outline-none"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1 uppercase tracking-wider">Depth (max_depth)</label>
          <input 
            type="number" 
            value={maxDepth} 
            onChange={(e) => setMaxDepth(e.target.value)}
            className="w-full bg-gray-900 border border-gray-600 rounded px-2 py-1 text-sm text-white focus:border-blue-500 outline-none"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1 uppercase tracking-wider">Test Size ({testSize})</label>
          <input 
            type="range" 
            min="0.1" 
            max="0.5" 
            step="0.05"
            value={testSize} 
            onChange={(e) => setTestSize(e.target.value)}
            className="w-full h-2 bg-gray-900 rounded-lg appearance-none cursor-pointer accent-blue-500 mt-2"
          />
        </div>
      </div>

      {error && (
        <div className="p-3 mb-4 bg-red-900/30 border border-red-700 rounded text-red-200 text-sm">
          <strong>Error:</strong> {error}
        </div>
      )}

      {result && (
        <div className="space-y-3 text-sm animate-fade-in">
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-gray-700/50 p-3 rounded border border-gray-600">
              <span className="block text-gray-400 text-xs uppercase tracking-wider">Precisión (Accuracy)</span>
              <span className="text-2xl font-mono text-green-400 font-bold">
                {(result.accuracy * 100).toFixed(1)}%
              </span>
            </div>
            <div className="bg-gray-700/50 p-3 rounded border border-gray-600">
              <span className="block text-gray-400 text-xs uppercase tracking-wider">Muestras (Barras)</span>
              <span className="text-2xl font-mono text-white font-bold">{result.samples}</span>
            </div>
          </div>

          {result.confusion_matrix && (
            <div className="bg-gray-700/50 p-3 rounded border border-gray-600">
              <span className="block text-gray-400 text-xs uppercase tracking-wider mb-2">Matriz de Confusión</span>
              <div className="grid grid-cols-2 gap-2 text-center text-xs">
                <div className="bg-gray-800 p-2 rounded border border-gray-600">
                  <div className="text-gray-500 text-[10px]">TN (0/0)</div>
                  <div className="text-white font-mono text-lg">{result.confusion_matrix[0][0]}</div>
                </div>
                <div className="bg-gray-800 p-2 rounded border border-gray-600">
                  <div className="text-gray-500 text-[10px]">FP (0/1)</div>
                  <div className="text-white font-mono text-lg">{result.confusion_matrix[0][1]}</div>
                </div>
                <div className="bg-gray-800 p-2 rounded border border-gray-600">
                  <div className="text-gray-500 text-[10px]">FN (1/0)</div>
                  <div className="text-white font-mono text-lg">{result.confusion_matrix[1][0]}</div>
                </div>
                <div className="bg-gray-800 p-2 rounded border border-gray-600">
                  <div className="text-gray-500 text-[10px]">TP (1/1)</div>
                  <div className="text-white font-mono text-lg">{result.confusion_matrix[1][1]}</div>
                </div>
              </div>
            </div>
          )}

          {/* ... resto del componente ... */}
          {/* Se omite el resto por brevedad, asumiendo que es idéntico al original pero en la nueva ruta */}
          <div className="bg-gray-700/50 p-3 rounded border border-gray-600">
            <span className="block text-gray-400 text-xs uppercase tracking-wider mb-2">Features Utilizadas</span>
            <div className="flex flex-wrap gap-2">
              {result.features && result.features.map((feat, idx) => (
                <span key={idx} className="px-2 py-1 bg-gray-600 rounded text-xs font-mono text-blue-200 border border-gray-500">
                  {feat}
                </span>
              ))}
            </div>
          </div>
        </div>
      )}
      
      {!result && !loading && !error && (
        <div className="text-gray-500 text-sm italic text-center py-6 bg-gray-900/20 rounded border border-dashed border-gray-700">
          Presiona "Iniciar Entrenamiento" para generar un nuevo modelo basado en los datos históricos.
        </div>
      )}
    </div>
  );
};

export default MLTrainingPanel;