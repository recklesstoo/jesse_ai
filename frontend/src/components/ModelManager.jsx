import React, { useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

const ModelManager = ({ botId = 'bot-1', onToast }) => {
  const [backups, setBackups] = useState([]);
  const [loading, setLoading] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [error, setError] = useState(null);
  const [successMsg, setSuccessMsg] = useState(null);

  const fetchBackups = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/ml/backups`);
      if (res.ok) {
        const data = await res.json();
        setBackups(data.backups || []);
      }
    } catch (err) {
      setError("Error cargando backups.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchBackups();
  }, []);

  const handleRestore = async (folder, filename) => {
    if (!confirm(`¿Restaurar ${filename} del backup ${folder}? Se sobrescribirá el modelo actual.`)) return;
    
    setRestoring(true);
    setError(null);
    setSuccessMsg(null);
    
    try {
      const res = await fetch(`${API_BASE}/api/v1/ml/restore`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ botId, folder, filename })
      });
      const data = await res.json();
      if (data.ok) {
        setSuccessMsg(`Modelo restaurado exitosamente desde ${folder}`);
        if (onToast) onToast(`Modelo restaurado desde ${folder}`, "success");
      } else {
        const errMsg = data.error || "Error al restaurar.";
        setError(errMsg);
        if (onToast) onToast(errMsg, "error");
      }
    } catch (err) {
      setError("Error de conexión.");
      if (onToast) onToast("Error de conexión al restaurar.", "error");
    } finally {
      setRestoring(false);
    }
  };

  const formatTs = (ts) => {
    // yyyyMMdd_HHmmss
    if (!ts || ts.length !== 15) return ts;
    const y = ts.substring(0, 4);
    const m = ts.substring(4, 6);
    const d = ts.substring(6, 8);
    const H = ts.substring(9, 11);
    const M = ts.substring(11, 13);
    const S = ts.substring(13, 15);
    return `${y}-${m}-${d} ${H}:${M}:${S}`;
  };

  return (
    <div className="p-4 bg-gray-800 rounded-lg border border-gray-700 text-white shadow-md mt-4">
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-bold text-purple-400 flex items-center gap-2">
          📦 Backups & Restauración
        </h3>
        <button 
          onClick={fetchBackups} 
          className="text-xs bg-gray-700 hover:bg-gray-600 px-2 py-1 rounded border border-gray-600 transition-colors"
        >
          Refrescar
        </button>
      </div>

      {error && (
        <div className="p-2 mb-3 bg-red-900/30 border border-red-700 rounded text-red-200 text-xs">
          {error}
        </div>
      )}
      
      {successMsg && (
        <div className="p-2 mb-3 bg-green-900/30 border border-green-700 rounded text-green-200 text-xs">
          {successMsg}
        </div>
      )}

      {loading && <div className="text-gray-400 text-sm italic">Cargando backups...</div>}

      {!loading && backups.length === 0 && (
        <div className="text-gray-500 text-sm italic">No se encontraron backups.</div>
      )}

      <div className="space-y-2 max-h-60 overflow-y-auto pr-1 custom-scrollbar">
        {backups.map((bk) => (
          <div key={bk.folder} className="bg-gray-700/30 p-2 rounded border border-gray-600/50">
            <div className="text-xs text-gray-400 font-mono mb-1 border-b border-gray-600/50 pb-1 flex justify-between">
              <span>{formatTs(bk.timestamp)}</span>
              <span className="opacity-50">{bk.folder}</span>
            </div>
            <div className="space-y-1 mt-1">
              {bk.models.map((model) => (
                <div key={model} className="flex justify-between items-center text-sm">
                  <span className="text-gray-200">{model}</span>
                  {model.includes(botId) && (
                    <button
                      onClick={() => handleRestore(bk.folder, model)}
                      disabled={restoring}
                      className="px-2 py-0.5 bg-purple-700 hover:bg-purple-600 text-white text-xs rounded transition-colors disabled:opacity-50"
                    >
                      Restaurar
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default ModelManager;