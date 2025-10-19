import { useState, useEffect } from 'react';

function ReportCrowdPopup( { showPopup } ) {

  useEffect(() => {
      console.log(showPopup)
  }, [])

  return (
    <div>
      {showPopup && (
            <div className=' mt-2 bg-white p-4'>
                <p className='font-semibold '>Transit Details:</p>
                <div className='space-y-2 max-h-40 overflow-y-auto'>
                  
                </div>
              </div>
      )}
      </div>);
}

export default ReportCrowdPopup;
