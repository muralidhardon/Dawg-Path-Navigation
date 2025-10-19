import React, { useState, useEffect } from 'react'
import { useLoadScript } from '@react-google-maps/api'
import './App.css'
import Map from './components/Map'
import Search from './components/Search'

const libraries = ['places', 'visualization']

function App() {
  const [search, setSearch] = useState({ 
    lat: 47.6567, 
    lng: -122.3066, 
    name: "University of Washington", 
    address: "1410 NE Campus Pkwy, Seattle, WA 98195" 
  })
  const [userLocation, setUserLocation] = useState(null)
  const [isReportingCrowd, setIsReportingCrowd] = useState(false)
  const [isReportingDanger, setIsReportingDanger] = useState(false)
  const [isAddingEvent, setIsAddingEvent] = useState(false)
  const [crowdLocation, setCrowdLocation] = useState(null)
  const [dangerLocation, setDangerLocation] = useState(null)
  const [eventLocation, setEventLocation] = useState(null)
  const [dangerRadius, setDangerRadius] = useState(50)
  const [dangerLevel, setDangerLevel] = useState(5)
  const [routeInfo, setRouteInfo] = useState(null)
  
  // Event form state
  const [eventName, setEventName] = useState('')
  const [eventType, setEventType] = useState('concert')
  const [eventTime, setEventTime] = useState('')
  const [eventNotes, setEventNotes] = useState('')
  const [todayEvents, setTodayEvents] = useState([])

  const { isLoaded } = useLoadScript({
    googleMapsApiKey: import.meta.env.VITE_GOOGLE_MAPS_API_KEY,
    libraries: libraries
  })

  useEffect(() => {
    if (!navigator.geolocation) {
      console.error('Geolocation not supported')
      setUserLocation({ lat: 47.6567, lng: -122.3066 })
      return
    }

    // First try to get current position
    navigator.geolocation.getCurrentPosition(
      (position) => {
        console.log('Got initial location:', position.coords.latitude, position.coords.longitude)
        setUserLocation({
          lat: position.coords.latitude,
          lng: position.coords.longitude
        })
      },
      (error) => {
        console.error('Geolocation error on initial request:', error.message)
        setUserLocation({ lat: 47.6567, lng: -122.3066 })
      },
      { 
        enableHighAccuracy: true,
        timeout: 10000,
        maximumAge: 0
      }
    )

    // Then watch for location updates
    const watchId = navigator.geolocation.watchPosition(
      (position) => {
        console.log('Location updated:', position.coords.latitude, position.coords.longitude)
        setUserLocation({
          lat: position.coords.latitude,
          lng: position.coords.longitude
        })
      },
      (error) => {
        console.error('Geolocation watch error:', error.message)
      },
      { 
        enableHighAccuracy: true,
        timeout: 10000,
        maximumAge: 5000
      }
    )

    return () => navigator.geolocation.clearWatch(watchId)
  }, [])

  const handleConfirmCrowd = async () => {
    if (!crowdLocation) {
      alert('Please select a location on the map')
      return
    }

    try {
      const response = await fetch('http://localhost:8000/api/report-crowd', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          location: crowdLocation,
          timestamp: new Date().toISOString(),
          userLocation: userLocation
        })
      })

      const data = await response.json()
      console.log('Crowd report submitted:', data)
      
      setIsReportingCrowd(false)
      setCrowdLocation(null)
      alert('Crowd report submitted successfully!')
      
    } catch (error) {
      console.error('Error submitting crowd report:', error)
      alert('Failed to submit crowd report')
    }
  }

  const handleConfirmDanger = async () => {
    if (!dangerLocation) {
      alert('Please select a location on the map')
      return
    }

    try {
      const response = await fetch('http://localhost:8000/api/report-danger', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          location: dangerLocation,
          radius: dangerRadius,
          dangerLevel: dangerLevel,
          timestamp: new Date().toISOString(),
          userLocation: userLocation
        })
      })

      const data = await response.json()
      console.log('Danger report submitted:', data)
      
      setIsReportingDanger(false)
      setDangerLocation(null)
      setDangerRadius(50)
      setDangerLevel(5)
      alert('Danger area reported successfully!')
      
    } catch (error) {
      console.error('Error submitting danger report:', error)
      alert('Failed to submit danger report')
    }
  }

  const handleConfirmEvent = async () => {
    if (!eventLocation) {
      alert('Please select a location on the map')
      return
    }

    if (!eventName || !eventTime) {
      alert('Please fill in event name and time')
      return
    }

    try {
      const response = await fetch('http://localhost:8000/api/add-event', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: eventName,
          location: eventLocation,
          type: eventType,
          time: eventTime,
          notes: eventNotes,
          timestamp: new Date().toISOString(),
          userLocation: userLocation
        })
      })

      const data = await response.json()
      console.log('Event added:', data)
      
      // Reset form
      setIsAddingEvent(false)
      setEventLocation(null)
      setEventName('')
      setEventType('concert')
      setEventTime('')
      setEventNotes('')
      alert('Event added successfully!')
      
    } catch (error) {
      console.error('Error adding event:', error)
      alert('Failed to add event')
    }
  }

  const placeSelect = (location) => {
    console.log(location)
    setSearch(location)
  }

  // Listen for event navigation requests from map
  useEffect(() => {
    const handleNavigateToEvent = (e) => {
      const event = e.detail
      setSearch({
        lat: event.location.lat,
        lng: event.location.lng,
        name: event.name,
        address: `${event.type} - ${new Date(event.time).toLocaleTimeString()}`
      })
    }
    
    window.addEventListener('navigateToEvent', handleNavigateToEvent)
    return () => window.removeEventListener('navigateToEvent', handleNavigateToEvent)
  }, [])

  // Fetch today's events for sidebar
  useEffect(() => {
    const fetchTodayEvents = async () => {
      try {
        const response = await fetch('http://localhost:8000/api/events')
        if (!response.ok) return
        
        const data = await response.json()
        
        // Filter events for today
        const today = new Date()
        today.setHours(0, 0, 0, 0)
        
        const eventsToday = data.filter(event => {
          const eventDate = new Date(event.time)
          eventDate.setHours(0, 0, 0, 0)
          return eventDate.getTime() === today.getTime()
        })
        
        setTodayEvents(eventsToday)
      } catch (error) {
        console.error('Error fetching events:', error)
        setTodayEvents([])
      }
    }
    fetchTodayEvents()
    
    // Refresh events every 60 seconds
    const interval = setInterval(fetchTodayEvents, 60000)
    return () => clearInterval(interval)
  }, [])

  if (!isLoaded || !userLocation) {
    return <div className='flex items-center justify-center h-screen'>Loading...</div>
  }

  return (
    <div className=''>
      <div className='flex flex-row'>
        <div className='flex-1 relative'>
          <Map 
            destination={{ lat: search.lat, lng: search.lng }} 
            origin={userLocation}
            isReportingCrowd={isReportingCrowd}
            onCrowdLocationSet={setCrowdLocation}
            isReportingDanger={isReportingDanger}
            onDangerLocationSet={setDangerLocation}
            isAddingEvent={isAddingEvent}
            onEventLocationSet={setEventLocation}
            dangerRadius={dangerRadius}
            dangerLevel={dangerLevel}
            onRouteInfo={setRouteInfo}
          />
        </div>
        
        <div className='w-1/3 bg-purple-950 p-6 overflow-y-auto h-screen flex flex-col text-white pointer-events-auto'>
          <span className='flex justify-between items-center w-full'>
            <h2 className='text-2xl font-bold mb-4'>Where to?</h2>
            <img src='/logo.png' className='h-8 mb-4' alt='logo' />
          </span>
          
          {/* Crowd Reporting Mode */}
          {isReportingCrowd && (
            <div className='mb-6 p-4 bg-red-900 rounded-lg'>
              <h3 className='font-bold mb-2'>Report Crowded Area</h3>
              <p className='text-sm text-gray-300 mb-3'>
                Drag the marker on the map to the exact crowd location (within 100m)
              </p>
              {crowdLocation && (
                <p className='text-xs text-green-300 mb-3'>
                  ✓ Location selected
                </p>
              )}
              <div className='flex gap-2'>
                <button
                  onClick={handleConfirmCrowd}
                  className='flex-1 bg-green-500 text-white py-2 px-4 rounded-lg hover:bg-green-600 transition disabled:bg-gray-600 disabled:cursor-not-allowed'
                  disabled={!crowdLocation}
                >
                  ✓ Confirm
                </button>
                <button
                  onClick={() => {
                    setIsReportingCrowd(false)
                    setCrowdLocation(null)
                  }}
                  className='flex-1 bg-gray-500 text-white py-2 px-4 rounded-lg hover:bg-gray-600 transition'
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {/* Danger Reporting Mode */}
          {isReportingDanger && (
            <div className='mb-6 p-4 bg-orange-900 rounded-lg'>
              <h3 className='font-bold mb-2'>⚠️ Report Danger Area</h3>
              <p className='text-sm text-gray-300 mb-3'>
                Drag the marker to the danger location and adjust settings
              </p>
              
              {dangerLocation && (
                <p className='text-xs text-green-300 mb-3'>
                  ✓ Location selected
                </p>
              )}

              <div className='mb-4'>
                <label className='text-sm font-semibold mb-2 block'>
                  Danger Radius: {dangerRadius}m
                </label>
                <input
                  type="range"
                  min="25"
                  max="150"
                  value={dangerRadius}
                  onChange={(e) => setDangerRadius(parseInt(e.target.value))}
                  className='w-full h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer'
                />
                <div className='flex justify-between text-xs text-gray-400 mt-1'>
                  <span>25m</span>
                  <span>150m</span>
                </div>
              </div>

              <div className='mb-4'>
                <label className='text-sm font-semibold mb-2 block'>
                  Danger Level: {dangerLevel}/10
                </label>
                <input
                  type="range"
                  min="1"
                  max="10"
                  value={dangerLevel}
                  onChange={(e) => setDangerLevel(parseInt(e.target.value))}
                  className='w-full h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer'
                />
                <div className='flex justify-between text-xs text-gray-400 mt-1'>
                  <span>Low (1)</span>
                  <span>Critical (10)</span>
                </div>
              </div>

              <div className='flex gap-2'>
                <button
                  onClick={handleConfirmDanger}
                  className='flex-1 bg-green-500 text-white py-2 px-4 rounded-lg hover:bg-green-600 transition disabled:bg-gray-600 disabled:cursor-not-allowed'
                  disabled={!dangerLocation}
                >
                  ✓ Confirm
                </button>
                <button
                  onClick={() => {
                    setIsReportingDanger(false)
                    setDangerLocation(null)
                    setDangerRadius(50)
                    setDangerLevel(5)
                  }}
                  className='flex-1 bg-gray-500 text-white py-2 px-4 rounded-lg hover:bg-gray-600 transition'
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {/* Add Event Mode */}
          {isAddingEvent && (
            <div className='mb-6 p-4 bg-blue-900 rounded-lg'>
              <h3 className='font-bold mb-2'>🎉 Add Event</h3>
              <p className='text-sm text-gray-300 mb-3'>
                Drag the marker to the event location and fill in details
              </p>
              
              {eventLocation && (
                <p className='text-xs text-green-300 mb-3'>
                  ✓ Location selected
                </p>
              )}

              {/* Event Name */}
              <div className='mb-3'>
                <label className='text-sm font-semibold mb-1 block'>Event Name *</label>
                <input
                  type="text"
                  placeholder="e.g., Summer Music Festival"
                  value={eventName}
                  onChange={(e) => setEventName(e.target.value)}
                  className='w-full px-3 py-2 bg-gray-800 border border-gray-600 rounded-lg text-white focus:border-blue-500 focus:outline-none'
                />
              </div>

              {/* Event Type */}
              <div className='mb-3'>
                <label className='text-sm font-semibold mb-1 block'>Event Type</label>
                <select
                  value={eventType}
                  onChange={(e) => setEventType(e.target.value)}
                  className='w-full px-3 py-2 bg-gray-800 border border-gray-600 rounded-lg text-white focus:border-blue-500 focus:outline-none'
                >
                  <option value="concert">Concert</option>
                  <option value="festival">Festival</option>
                  <option value="sports">Sports</option>
                  <option value="market">Market</option>
                  <option value="exhibition">Exhibition</option>
                  <option value="parade">Parade</option>
                  <option value="other">Other</option>
                </select>
              </div>

              {/* Event Time */}
              <div className='mb-3'>
                <label className='text-sm font-semibold mb-1 block'>Event Time *</label>
                <input
                  type="datetime-local"
                  value={eventTime}
                  onChange={(e) => setEventTime(e.target.value)}
                  className='w-full px-3 py-2 bg-gray-800 border border-gray-600 rounded-lg text-white focus:border-blue-500 focus:outline-none'
                />
              </div>

              {/* Additional Notes */}
              <div className='mb-3'>
                <label className='text-sm font-semibold mb-1 block'>Additional Notes</label>
                <textarea
                  placeholder="Add any additional details..."
                  value={eventNotes}
                  onChange={(e) => setEventNotes(e.target.value)}
                  rows={3}
                  className='w-full px-3 py-2 bg-gray-800 border border-gray-600 rounded-lg text-white focus:border-blue-500 focus:outline-none resize-none'
                />
              </div>

              <div className='flex gap-2'>
                <button
                  onClick={handleConfirmEvent}
                  className='flex-1 bg-green-500 text-white py-2 px-4 rounded-lg hover:bg-green-600 transition disabled:bg-gray-600 disabled:cursor-not-allowed'
                  disabled={!eventLocation || !eventName || !eventTime}
                >
                  ✓ Add Event
                </button>
                <button
                  onClick={() => {
                    setIsAddingEvent(false)
                    setEventLocation(null)
                    setEventName('')
                    setEventType('concert')
                    setEventTime('')
                    setEventNotes('')
                  }}
                  className='flex-1 bg-gray-500 text-white py-2 px-4 rounded-lg hover:bg-gray-600 transition'
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {!isReportingCrowd && !isReportingDanger && !isAddingEvent && (
            <>
              <Search onPlaceSelect={placeSelect} />

              <div className='mt-6'>
                <h3 className='text-xl font-semibold mb-4'>Events Today</h3>
                
                {todayEvents.length === 0 ? (
                  <p className='text-gray-400 text-sm'>No events today</p>
                ) : (
                  <div className='space-y-3 max-h-96 overflow-y-auto'>
                    {todayEvents.map((event, idx) => (
                      <div 
                        key={idx}
                        onClick={() => {
                          setSearch({
                            lat: event.location.lat,
                            lng: event.location.lng,
                            name: event.name,
                            address: `${event.type} - ${new Date(event.time).toLocaleTimeString()}`
                          })
                          window.dispatchEvent(new CustomEvent('navigateToEvent', { detail: event }))
                        }}
                        className='bg-white p-3 rounded-lg hover:bg-gray-100 cursor-pointer transition border border-gray-300'
                      >
                        <h4 className='font-semibold text-gray-800'>{event.name}</h4>
                        <div className='flex justify-between mt-2 text-xs text-gray-600'>
                          <span>📍 {event.type}</span>
                          <span>⏱️ {new Date(event.time).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}</span>
                        </div>
                        {event.notes && (
                          <p className='text-xs text-gray-500 mt-2'>{event.notes.substring(0, 60)}...</p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}

          <div className='mt-auto justify text-center space-y-2'>
            <p 
              className='hover:text-gray-400 cursor-pointer' 
              onClick={() => setIsAddingEvent(true)}
            >
              I want to add an event.
            </p>
            <p 
              className='hover:text-gray-400 cursor-pointer' 
              onClick={() => setIsReportingCrowd(true)}
            >
              I want to report a crowded area.
            </p> 
            <p 
              className='hover:text-gray-400 cursor-pointer'
              onClick={() => setIsReportingDanger(true)}
            >
              I want to report a dangerous area.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

export default App