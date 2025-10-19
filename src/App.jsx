import React, { useState } from 'react'
import { GoogleMap, LoadScript, Marker } from '@react-google-maps/api'
import './App.css'

const containerStyle = {
  width: '100%',
  height: '100vh'
}

const center = {
  lat: 47.6062,
  lng: -122.3321
}

function App() {
  return (
    <div className=''>
      <div className='flex flex-row'>
        <div className='w-screen'>
          <LoadScript googleMapsApiKey={"AIzaSyAMKTZ8m3DITM2OuXQ7xJ70v7YAIRHagZg"}>
            <GoogleMap
              mapContainerStyle={containerStyle}
              center={center}
              zoom={12}
            >
              <Marker position={center} />
            </GoogleMap>
          </LoadScript>
        </div>
        <div className='w-1/3 bg-purple-950 p-6 overflow-y-auto h-screen text-white'>
          <h2 className='text-2xl font-bold mb-4'>Where to?</h2>
          
          <div className='mb-6'>
            <input
              type="text"
              placeholder="Search destination..."
              className='w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:border-blue-500 focus:outline-none'
            />
          </div>

          <div className='justify justify-center'>
            <h3 className='text-xl font-semibold mb-4 '>Events Nearby</h3>
            
            <div className='space-y-3'>
              <div className='bg-gray-50 p-4 rounded-lg hover:bg-gray-100 cursor-pointer transition border border-gray-200'>
                <h4 className='font-semibold text-lg text-gray-600'>Pike Place Market</h4>
                <div className='flex justify-between mt-2 text-sm text-gray-600'>
                  <span>📍 0.5 miles</span>
                  <span>⏱️ 5 min walk</span>
                </div>
              </div>

              <div className='bg-gray-50 p-4 rounded-lg hover:bg-gray-100 cursor-pointer transition border border-gray-200'>
                <h4 className='font-semibold text-lg text-gray-600'>Space Needle</h4>
                <div className='flex justify-between mt-2 text-sm text-gray-600'>
                  <span>📍 1.2 miles</span>
                  <span>⏱️ 15 min drive</span>
                </div>
              </div>

              <div className='bg-gray-50 p-4 rounded-lg hover:bg-gray-100 cursor-pointer transition border border-gray-200'>
                <h4 className='font-semibold text-lg text-gray-800'>Seattle Aquarium</h4>
                <div className='flex justify-between mt-2 text-sm text-gray-600'>
                  <span>📍 0.8 miles</span>
                  <span>⏱️ 10 min walk</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default App