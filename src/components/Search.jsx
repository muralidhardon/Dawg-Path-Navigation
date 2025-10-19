import React, { useState } from 'react'
import { Autocomplete } from '@react-google-maps/api'

function Search({ onPlaceSelect }) {
  const [autocomplete, setAutocomplete] = useState(null)
  

  const onLoad = (autocompleteObj) => {
    setAutocomplete(autocompleteObj)
  }

  const onPlaceChanged = () => {
    if (autocomplete !== null) {
      const place = autocomplete.getPlace()
      
      if (place.geometry) {
        const location = {
          lat: place.geometry.location.lat(),
          lng: place.geometry.location.lng(),
          name: place.name,
          address: place.formatted_address
        }
        onPlaceSelect(location)
      }
    }
  }

  return (
    <>
        <Autocomplete onLoad={onLoad} onPlaceChanged={onPlaceChanged}>
        <input
            type="text"
            placeholder="Search destination..."
            className='w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:border-white focus:outline-none'
        />
        </Autocomplete>
    </>
  )
}

export default Search