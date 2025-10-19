import React, { useState, useEffect, useRef } from 'react'
import { GoogleMap, DirectionsRenderer, Marker, HeatmapLayer, Circle } from '@react-google-maps/api'

const containerStyle = {
  width: '100%',
  height: '100vh'
}

function Map({ 
  origin = { lat: 47.6567, lng: -122.3066 }, 
  destination, 
  travelMode = 'TRANSIT', 
  onRouteInfo, 
  isReportingCrowd, 
  onCrowdLocationSet,
  isReportingDanger,
  onDangerLocationSet,
  isAddingEvent,
  onEventLocationSet,
  dangerRadius = 50,
  dangerLevel = 5
}) {
  const [directions, setDirections] = useState(null)
  const [routeInfo, setRouteInfo] = useState(null)
  const [error, setError] = useState(null)
  const directionsServiceRef = useRef(null)

  const [crowdMarker, setCrowdMarker] = useState(null)
  const [dangerMarker, setDangerMarker] = useState(null)
  const [eventMarker, setEventMarker] = useState(null)
  const [isDragging, setIsDragging] = useState(false)
  const [crowdLocations, setCrowdLocations] = useState([])
  const [dangerZones, setDangerZones] = useState([])
  const [selectedDangerZone, setSelectedDangerZone] = useState(null)
  const [todayEvents, setTodayEvents] = useState([])
  const [selectedEvent, setSelectedEvent] = useState(null)
  const mapRef = useRef(null)

  const onCrowdMarkerDragEnd = (e) => {
    const newLat = e.latLng.lat()
    const newLng = e.latLng.lng()
    
    const distance = getDistance(origin, { lat: newLat, lng: newLng })
    const maxRadius = 100
    
    if (distance <= maxRadius) {
      setCrowdMarker({ lat: newLat, lng: newLng })
      setIsDragging(false)
      if (onCrowdLocationSet) {
        onCrowdLocationSet({ lat: newLat, lng: newLng })
      }
    } else {
      alert('Location must be within 100 meters of your current location')
      setCrowdMarker({ lat: origin.lat, lng: origin.lng })
      setIsDragging(false)
    }
  }

  const onDangerMarkerDragEnd = (e) => {
    const newLat = e.latLng.lat()
    const newLng = e.latLng.lng()
    
    setDangerMarker({ lat: newLat, lng: newLng })
    setIsDragging(false)
    if (onDangerLocationSet) {
      onDangerLocationSet({ lat: newLat, lng: newLng })
    }
  }

  const onEventMarkerDragEnd = (e) => {
    const newLat = e.latLng.lat()
    const newLng = e.latLng.lng()
    
    setEventMarker({ lat: newLat, lng: newLng })
    setIsDragging(false)
    if (onEventLocationSet) {
      onEventLocationSet({ lat: newLat, lng: newLng })
    }
  }

  const getDistance = (point1, point2) => {
    const R = 6371e3
    const φ1 = point1.lat * Math.PI / 180
    const φ2 = point2.lat * Math.PI / 180
    const Δφ = (point2.lat - point1.lat) * Math.PI / 180
    const Δλ = (point2.lng - point1.lng) * Math.PI / 180

    const a = Math.sin(Δφ/2) * Math.sin(Δφ/2) +
              Math.cos(φ1) * Math.cos(φ2) *
              Math.sin(Δλ/2) * Math.sin(Δλ/2)
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a))

    return R * c
  }

  const getDangerColor = (level) => {
    if (level <= 3) return '#FFA500'
    if (level <= 6) return '#FF6B00'
    if (level <= 8) return '#FF4500'
    return '#FF0000'
  }

  // Fetch crowd locations from backend
  useEffect(() => {
    const fetchCrowdLocations = async () => {
      try {
        const response = await fetch('https://dubhacks-grow-1.onrender.com/api/crowds')
        const data = await response.json()
        setCrowdLocations(data)
      } catch (error) {
        console.error('Error fetching crowd locations:', error)
      }
    }
    fetchCrowdLocations()
  }, [])

  // Fetch danger zones from backend
  useEffect(() => {
    const fetchDangerZones = async () => {
      try {
        const response = await fetch('https://dubhacks-grow-1.onrender.com/api/dangers')
        console.log('Danger zones response status:', response.status)
        
        if (!response.ok) {
          console.error('Bad response status:', response.status)
          return
        }
        
        const data = await response.json()
        console.log('Fetched danger zones:', data)
        setDangerZones(data)
      } catch (error) {
        console.error('Error fetching danger zones:', error)
        setDangerZones([])
      }
    }
    fetchDangerZones()
    
    // Refresh danger zones every 30 seconds
    const interval = setInterval(fetchDangerZones, 30000)
    return () => clearInterval(interval)
  }, [])

  // Fetch today's events from backend
  useEffect(() => {
    const fetchTodayEvents = async () => {
      try {
        const response = await fetch('https://dubhacks-grow-1.onrender.com/api/events')
        console.log('Events response status:', response.status)
        
        if (!response.ok) {
          console.error('Bad response status:', response.status)
          return
        }
        
        const data = await response.json()
        console.log('All events from backend:', data)
        
        // Filter events for today
        const today = new Date()
        today.setHours(0, 0, 0, 0)
        
        const eventsToday = data.filter(event => {
          const eventDate = new Date(event.time)
          eventDate.setHours(0, 0, 0, 0)
          console.log('Comparing event date:', eventDate, 'with today:', today)
          return eventDate.getTime() === today.getTime()
        })
        
        console.log('Filtered today\'s events:', eventsToday)
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

  // Convert crowd locations to heatmap data
  const heatmapData = crowdLocations.map(crowd => ({
    location: new google.maps.LatLng(crowd.location.lat, crowd.location.lng),
    weight: 0.7
  }))

  useEffect(() => {
    if (isReportingCrowd && origin) {
      setCrowdMarker({ lat: origin.lat, lng: origin.lng })
    } else if (!isReportingCrowd) {
      setCrowdMarker(null)
    }
  }, [isReportingCrowd, origin])

  useEffect(() => {
    if (isReportingDanger && origin) {
      setDangerMarker({ lat: origin.lat, lng: origin.lng })
    } else if (!isReportingDanger) {
      setDangerMarker(null)
    }
  }, [isReportingDanger, origin])

  useEffect(() => {
    if (isAddingEvent && origin) {
      setEventMarker({ lat: origin.lat, lng: origin.lng })
    } else if (!isAddingEvent) {
      setEventMarker(null)
    }
  }, [isAddingEvent, origin])

  useEffect(() => {
    if (isReportingCrowd || isReportingDanger || isAddingEvent) return
    
    if (!origin || !destination) return
    
    if (!directionsServiceRef.current) {
      directionsServiceRef.current = new google.maps.DirectionsService()
    }

    directionsServiceRef.current.route(
      {
        origin: origin,
        destination: destination,
        travelMode: google.maps.TravelMode[travelMode],
        transitOptions: {
          departureTime: new Date(),
        },
      },
      (result, status) => {
        if (status === google.maps.DirectionsStatus.OK) {
          setDirections(result)
          setError(null)
          
          const leg = result.routes[0].legs[0]
          const info = {
            duration: leg.duration.text,
            distance: leg.distance.text,
            startAddress: leg.start_address,
            endAddress: leg.end_address,
            steps: leg.steps.map(step => ({
              instructions: step.instructions,
              distance: step.distance.text,
              duration: step.duration.text,
              travelMode: step.travel_mode,
              transitDetails: step.transit ? {
                line: step.transit.line.short_name || step.transit.line.name,
                vehicle: step.transit.line.vehicle.type,
                departure: step.transit.departure_time.text,
                arrival: step.transit.arrival_time.text,
                numStops: step.transit.num_stops,
              } : null
            }))
          }
          
          setRouteInfo(info)
          if (onRouteInfo) onRouteInfo(info)
          
        } else {
          setError('Could not calculate route')
          console.error('Directions request failed:', status)
        }
      }
    )
  }, [destination?.lat, destination?.lng, travelMode])

  const center = origin || { lat: 47.6567, lng: -122.3066 }

  return (
    <div className='relative w-full h-full'>
      <GoogleMap
        ref={mapRef}
        mapContainerStyle={containerStyle}
        center={center}
        zoom={isReportingCrowd || isReportingDanger || isAddingEvent ? 16 : 12}
        options={{
          zoomControl: true,
          zoomControlOptions: {
            position: google.maps.ControlPosition.RIGHT_CENTER,
          },
          streetViewControl: false,
          mapTypeControl: false,
          fullscreenControl: true,
          gestureHandling: 'auto',
        }}
      >
        {directions && !isReportingCrowd && !isReportingDanger && !isAddingEvent && (
          <DirectionsRenderer 
            directions={directions}
            options={{
              suppressMarkers: false,
              polylineOptions: {
                strokeColor: '#7341b5',
                strokeWeight: 5
              }
            }}
          />
        )}

        {heatmapData.length > 0 && !isReportingCrowd && !isReportingDanger && !isAddingEvent && (
          <HeatmapLayer
            data={heatmapData}
            options={{
              radius: 45,
              opacity: 0.6,
              gradient: [
                "rgba(255, 215, 0, 0)",
                "rgba(255, 215, 0, 0.3)",
                "rgba(255, 220, 50, 0.6)",
                "rgba(255, 230, 80, 0.8)",
                "rgba(255, 240, 120, 1)",
                "rgba(255, 255, 200, 1)",
                "rgba(255, 255, 255, 1)",
              ],
            }}
          />
        )}

        {/* Display today's events as markers */}
        {todayEvents && todayEvents.length > 0 && (
          todayEvents.map((event, idx) => (
            <Marker
              key={`event-${idx}`}
              position={{
                lat: event.location.lat,
                lng: event.location.lng
              }}
              icon={{
                path: google.maps.SymbolPath.CIRCLE,
                scale: 10,
                fillColor: '#4169E1',
                fillOpacity: 0.9,
                strokeColor: '#fff',
                strokeWeight: 2,
              }}
              onClick={() => setSelectedEvent(event)}
              title={event.name}
            />
          ))
        )}
        {dangerZones && dangerZones.length > 0 && (
          dangerZones.map((zone, idx) => (
            <Circle
              key={`danger-${idx}`}
              center={{
                lat: zone.location.lat,
                lng: zone.location.lng
              }}
              radius={zone.radius}
              options={{
                fillColor: getDangerColor(zone.dangerLevel),
                fillOpacity: 0.3,
                strokeColor: getDangerColor(zone.dangerLevel),
                strokeOpacity: 0.8,
                strokeWeight: 2.5,
                clickable: true,
              }}
              onClick={() => setSelectedDangerZone(zone)}
            />
          ))
        )}

        {/* Crowd Reporting UI */}
        {isReportingCrowd && crowdMarker && (
          <>
            <Circle
              center={origin}
              radius={100}
              options={{
                fillColor: '#7341b5',
                fillOpacity: 0.1,
                strokeColor: '#7341b5',
                strokeOpacity: 0.5,
                strokeWeight: 2,
              }}
            />
            
            <Marker
              position={origin}
              icon={{
                path: google.maps.SymbolPath.CIRCLE,
                scale: 8,
                fillColor: '#4285F4',
                fillOpacity: 1,
                strokeColor: '#fff',
                strokeWeight: 2,
              }}
              label={{
                text: '📍',
                fontSize: '20px'
              }}
            />

            <Marker
              position={crowdMarker}
              draggable={true}
              onDragStart={() => setIsDragging(true)}
              onDragEnd={onCrowdMarkerDragEnd}
              icon={{
                path: google.maps.SymbolPath.CIRCLE,
                scale: isDragging ? 15 : 12,
                fillColor: '#FF5733',
                fillOpacity: 0.8,
                strokeColor: '#fff',
                strokeWeight: 3,
              }}
              label={{
                text: '👥',
                fontSize: '24px'
              }}
            />
          </>
        )}

        {/* Danger Reporting UI */}
        {isReportingDanger && dangerMarker && (
          <>
            <Circle
              center={dangerMarker}
              radius={dangerRadius}
              options={{
                fillColor: getDangerColor(dangerLevel),
                fillOpacity: 0.2,
                strokeColor: getDangerColor(dangerLevel),
                strokeOpacity: 0.6,
                strokeWeight: 3,
              }}
            />
            
            <Marker
              position={origin}
              icon={{
                path: google.maps.SymbolPath.CIRCLE,
                scale: 8,
                fillColor: '#4285F4',
                fillOpacity: 1,
                strokeColor: '#fff',
                strokeWeight: 2,
              }}
              label={{
                text: '📍',
                fontSize: '20px'
              }}
            />

            <Marker
              position={dangerMarker}
              draggable={true}
              onDragStart={() => setIsDragging(true)}
              onDragEnd={onDangerMarkerDragEnd}
              icon={{
                path: google.maps.SymbolPath.CIRCLE,
                scale: isDragging ? 18 : 15,
                fillColor: getDangerColor(dangerLevel),
                fillOpacity: 0.9,
                strokeColor: '#fff',
                strokeWeight: 3,
              }}
              label={{
                text: '⚠️',
                fontSize: '28px'
              }}
            />
          </>
        )}

        {/* Event Adding UI */}
        {isAddingEvent && eventMarker && (
          <>
            <Marker
              position={origin}
              icon={{
                path: google.maps.SymbolPath.CIRCLE,
                scale: 8,
                fillColor: '#4285F4',
                fillOpacity: 1,
                strokeColor: '#fff',
                strokeWeight: 2,
              }}
              label={{
                text: '📍',
                fontSize: '20px'
              }}
            />

            <Marker
              position={eventMarker}
              draggable={true}
              onDragStart={() => setIsDragging(true)}
              onDragEnd={onEventMarkerDragEnd}
              icon={{
                path: google.maps.SymbolPath.CIRCLE,
                scale: isDragging ? 15 : 12,
                fillColor: '#4169E1',
                fillOpacity: 0.8,
                strokeColor: '#fff',
                strokeWeight: 3,
              }}
              label={{
                text: '🎉',
                fontSize: '24px'
              }}
            />
          </>
        )}
      </GoogleMap>

      {routeInfo && !isReportingCrowd && !isReportingDanger && !isAddingEvent && (
        <div className='absolute top-4 left-4 bg-white p-4 rounded-lg shadow-lg max-w-sm'>
          <div className='flex justify-between items-center mb-2'>
            <h3 className='font-bold text-lg'>Route Info</h3>
            <button 
              onClick={() => setRouteInfo(null)}
              className='text-gray-500 hover:text-gray-700'
            >
              ✕
            </button>
          </div>
          
          <div className='space-y-2 text-sm'>
            <div className='flex items-center gap-2'>
              <span className='font-semibold'>⏱️ Duration:</span>
              <span className='text-purple-600 font-bold'>{routeInfo.duration}</span>
            </div>
            
            <div className='flex items-center gap-2'>
              <span className='font-semibold'>📏 Distance:</span>
              <span>{routeInfo.distance}</span>
            </div>
            
            <div className='border-t pt-2 mt-2'>
              <p className='text-xs text-gray-600 mb-1'>From:</p>
              <p className='text-xs'>{routeInfo.startAddress}</p>
            </div>
            
            <div>
              <p className='text-xs text-gray-600 mb-1'>To:</p>
              <p className='text-xs'>{routeInfo.endAddress}</p>
            </div>

            {routeInfo.steps.some(s => s.transitDetails) && (
              <div className='border-t pt-2 mt-2'>
                <p className='font-semibold mb-2'>Transit Details:</p>
                <div className='space-y-2 max-h-40 overflow-y-auto'>
                  {routeInfo.steps
                    .filter(step => step.transitDetails)
                    .map((step, idx) => (
                      <div key={idx} className='bg-purple-50 p-2 rounded text-xs'>
                        <div className='font-semibold text-purple-700'>
                          🚌 {step.transitDetails.line} ({step.transitDetails.vehicle})
                        </div>
                        <div className='text-gray-600'>
                          {step.transitDetails.departure} → {step.transitDetails.arrival}
                        </div>
                        <div className='text-gray-500'>
                          {step.transitDetails.numStops} stops • {step.duration}
                        </div>
                      </div>
                    ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {selectedDangerZone && !isReportingCrowd && !isReportingDanger && !isAddingEvent && (
        <div className='absolute top-4 right-4 bg-white p-4 rounded-lg shadow-lg max-w-xs border-l-4' style={{borderColor: getDangerColor(selectedDangerZone.dangerLevel)}}>
          <div className='flex justify-between items-center mb-2'>
            <h3 className='font-bold text-lg'>⚠️ Danger Zone</h3>
            <button 
              onClick={() => setSelectedDangerZone(null)}
              className='text-gray-500 hover:text-gray-700'
            >
              ✕
            </button>
          </div>
          
          <div className='space-y-2 text-sm'>
            <div>
              <span className='font-semibold'>Danger Level:</span>
              <span className='ml-2 font-bold' style={{color: getDangerColor(selectedDangerZone.dangerLevel)}}>{selectedDangerZone.dangerLevel}/10</span>
            </div>
            
            <div>
              <span className='font-semibold'>Radius:</span>
              <span className='ml-2'>{selectedDangerZone.radius}m</span>
            </div>

            {selectedDangerZone.timestamp && (
              <div>
                <span className='font-semibold'>Reported:</span>
                <span className='ml-2 text-xs text-gray-600'>{new Date(selectedDangerZone.timestamp).toLocaleString()}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {selectedEvent && !isReportingCrowd && !isReportingDanger && !isAddingEvent && (
        <div className='absolute bottom-4 right-4 bg-white p-4 rounded-lg shadow-lg max-w-xs border-l-4 border-blue-500'>
          <div className='flex justify-between items-center mb-2'>
            <h3 className='font-bold text-lg'>🎉 {selectedEvent.name}</h3>
            <button 
              onClick={() => setSelectedEvent(null)}
              className='text-gray-500 hover:text-gray-700'
            >
              ✕
            </button>
          </div>
          
          <div className='space-y-2 text-sm'>
            <div>
              <span className='font-semibold'>Type:</span>
              <span className='ml-2 capitalize'>{selectedEvent.type}</span>
            </div>
            
            <div>
              <span className='font-semibold'>Time:</span>
              <span className='ml-2'>{new Date(selectedEvent.time).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}</span>
            </div>

            <div>
              <span className='font-semibold'>Location:</span>
              <span className='ml-2 text-xs text-gray-600'>{selectedEvent.location.lat.toFixed(4)}, {selectedEvent.location.lng.toFixed(4)}</span>
            </div>

            {selectedEvent.notes && (
              <div>
                <span className='font-semibold'>Notes:</span>
                <p className='text-xs text-gray-600 mt-1'>{selectedEvent.notes}</p>
              </div>
            )}

            <button
              onClick={() => {
                // Trigger route calculation by setting this as the destination
                window.dispatchEvent(new CustomEvent('navigateToEvent', { detail: selectedEvent }))
              }}
              className='w-full mt-3 bg-blue-500 text-white py-2 px-4 rounded-lg hover:bg-blue-600 transition text-sm font-semibold'
            >
              📍 Get Directions
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className='absolute top-4 left-4 bg-red-500 text-white p-2 rounded'>
          {error}
        </div>
      )}
    </div>
  )
}

export default Map