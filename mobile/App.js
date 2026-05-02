import React, { useState } from 'react';
import { SafeAreaView, View, Text, TextInput, TouchableOpacity, FlatList } from 'react-native';

const API_URL = process.env.EXPO_PUBLIC_API_URL;

export default function App() {
  const [text, setText] = useState('');
  const [captures, setCaptures] = useState([]);
  const [status, setStatus] = useState('');

  const createCapture = async () => {
    setStatus('Procesando...');
    const res = await fetch(`${API_URL}/app/api/captures`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ raw_input: text, input_type: 'text', source: 'manual' })
    });
    const capture = await res.json();
    await fetch(`${API_URL}/app/api/captures/${capture.id}/process`, { method: 'POST' });
    setCaptures([capture, ...captures]);
    setStatus('Detecté esto');
    setText('');
  };

  return <SafeAreaView style={{ flex: 1, backgroundColor: '#F3F6FB', padding: 16 }}>
    <Text style={{ fontSize: 28, fontWeight: '700', marginBottom: 12 }}>Hoy</Text>
    <TouchableOpacity onPress={createCapture} style={{ backgroundColor: '#6C8EF5', padding: 18, borderRadius: 14, marginBottom: 12 }}>
      <Text style={{ color: 'white', textAlign: 'center', fontSize: 18 }}>Capturar</Text>
    </TouchableOpacity>
    <TextInput value={text} onChangeText={setText} placeholder='Pegá mensaje, audio o screenshot...' style={{ backgroundColor: 'white', borderRadius: 12, padding: 14 }} />
    <Text style={{ marginVertical: 8 }}>{status}</Text>
    <FlatList data={captures} keyExtractor={(i) => i.id} renderItem={({ item }) => (
      <View style={{ backgroundColor: 'white', padding: 12, borderRadius: 10, marginBottom: 8 }}>
        <Text style={{ fontWeight: '600' }}>Pendiente de revisión</Text>
        <Text>{item.raw_input}</Text>
      </View>
    )} />
  </SafeAreaView>;
}
