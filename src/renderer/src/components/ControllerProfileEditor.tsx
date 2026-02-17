import { useState, useEffect } from 'react'
import { api } from '../lib/api'
import type { ControllerProfile } from '../types'

export default function ControllerProfileEditor(): JSX.Element {
  const [profiles, setProfiles] = useState<ControllerProfile[]>([])
  const [images, setImages] = useState<string[]>([])
  const [sounds, setSounds] = useState<string[]>([])
  const [editing, setEditing] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [editImg, setEditImg] = useState('')
  const [editSnd, setEditSnd] = useState('')

  useEffect(() => {
    api.getProfiles().then((p) => setProfiles(p as ControllerProfile[])).catch(console.error)
    api.getImages().then(setImages).catch(console.error)
    api.getSounds().then(setSounds).catch(console.error)
  }, [])

  const startEdit = (profile: ControllerProfile) => {
    setEditing(profile.unique_id)
    setEditName(profile.custom_name || '')
    setEditImg(profile.img_src)
    setEditSnd(profile.snd_src)
  }

  const saveEdit = async () => {
    if (!editing) return
    await api.updateProfile(editing, {
      custom_name: editName || null,
      img_src: editImg,
      snd_src: editSnd
    })
    setProfiles(
      profiles.map((p) =>
        p.unique_id === editing
          ? { ...p, custom_name: editName || undefined, img_src: editImg, snd_src: editSnd }
          : p
      )
    )
    setEditing(null)
  }

  return (
    <div>
      <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">
        Controller Profiles
      </h3>
      {profiles.length === 0 ? (
        <p className="text-gray-500 text-sm italic">No saved profiles yet</p>
      ) : (
        <div className="space-y-2">
          {profiles.map((profile) => (
            <div key={profile.unique_id} className="bg-gray-900 rounded-lg p-3">
              {editing === profile.unique_id ? (
                <div className="space-y-2">
                  <input
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    placeholder={profile.default_name}
                    className="w-full bg-gray-700 rounded px-2 py-1 text-sm"
                  />
                  <select
                    value={editImg}
                    onChange={(e) => setEditImg(e.target.value)}
                    className="w-full bg-gray-700 rounded px-2 py-1 text-sm"
                  >
                    {images.map((img) => (
                      <option key={img} value={img}>
                        {img}
                      </option>
                    ))}
                  </select>
                  <select
                    value={editSnd}
                    onChange={(e) => setEditSnd(e.target.value)}
                    className="w-full bg-gray-700 rounded px-2 py-1 text-sm"
                  >
                    {sounds.map((snd) => (
                      <option key={snd} value={snd}>
                        {snd}
                      </option>
                    ))}
                  </select>
                  <div className="flex gap-2">
                    <button
                      onClick={saveEdit}
                      className="px-3 py-1 text-xs bg-blue-600 rounded hover:bg-blue-500"
                    >
                      Save
                    </button>
                    <button
                      onClick={() => setEditing(null)}
                      className="px-3 py-1 text-xs bg-gray-700 rounded hover:bg-gray-600"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <div
                  className="flex items-center gap-2 cursor-pointer"
                  onClick={() => startEdit(profile)}
                >
                  <img
                    src={`http://127.0.0.1:8000/assets/images/${profile.img_src}`}
                    alt={profile.default_name}
                    className="w-8 h-8 object-contain"
                  />
                  <div>
                    <div className="text-sm">
                      {profile.custom_name || profile.default_name}
                    </div>
                    <div className="text-xs text-gray-500">{profile.unique_id}</div>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
