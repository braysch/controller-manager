import { useState, useEffect } from 'react'
import { api } from '../lib/api'
import type { ControllerProfile } from '../types'

interface ControllerProfileEditorProps {
  open: boolean
}

export default function ControllerProfileEditor({ open }: ControllerProfileEditorProps): JSX.Element {
  const [profiles, setProfiles] = useState<ControllerProfile[]>([])
  const [images, setImages] = useState<string[]>([])
  const [sounds, setSounds] = useState<string[]>([])
  const [editing, setEditing] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [editImg, setEditImg] = useState('')
  const [editSnd, setEditSnd] = useState('')
  const [editGuid, setEditGuid] = useState('')
  const [editTr2IsStart, setEditTr2IsStart] = useState(false)
  const [editPadLength, setEditPadLength] = useState(1)

  const MAC_RE = /^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$/i
  const resolveMac = (profile: ControllerProfile) =>
    profile.bluetooth_address ||
    (MAC_RE.test(profile.unique_id) ? profile.unique_id : null)

  useEffect(() => {
    if (!open) return
    api.getProfiles().then((p) => setProfiles(p as ControllerProfile[])).catch(console.error)
    api.getImages().then(setImages).catch(console.error)
    api.getSounds().then(setSounds).catch(console.error)
  }, [open])

  const startEdit = (profile: ControllerProfile) => {
    setEditing(profile.unique_id)
    setEditName(profile.custom_name || '')
    setEditImg(profile.img_src)
    setEditSnd(profile.snd_src)
    setEditGuid(profile.guid_override || '')
    setEditTr2IsStart(profile.tr2_is_start)
    setEditPadLength(profile.pad_length)
  }

  const saveEdit = async () => {
    if (!editing) return
    await api.updateProfile(editing, {
      custom_name: editName || null,
      img_src: editImg,
      snd_src: editSnd,
      guid_override: editGuid || null,
      pad_length: editPadLength,
      tr2_is_start: editTr2IsStart
    })
    setProfiles(
      profiles.map((p) =>
        p.unique_id === editing
          ? {
              ...p,
              custom_name: editName || undefined,
              img_src: editImg,
              snd_src: editSnd,
              guid_override: editGuid || undefined,
              tr2_is_start: editTr2IsStart,
              pad_length: editPadLength
            }
          : p
      )
    )
    setEditing(null)
  }

  const deleteProfile = async (uniqueId: string) => {
    if (!window.confirm('Are you sure you want to delete this profile? If the controller is connected, it will be reset to defaults.')) {
      return
    }
    await api.deleteProfile(uniqueId)
    const p = await api.getProfiles()
    setProfiles(p as ControllerProfile[])
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
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">GUID Override</label>
                    <input
                      value={editGuid}
                      onChange={(e) => setEditGuid(e.target.value)}
                      placeholder="Leave blank to use auto-detected GUID"
                      className="w-full bg-gray-700 rounded px-2 py-1 text-xs font-mono"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">MAC Address</label>
                    <input
                      readOnly
                      value={resolveMac(profile) ?? ''}
                      placeholder="Reconnect controller to capture"
                      className="w-full bg-gray-800 rounded px-2 py-1 text-xs font-mono text-gray-400 cursor-default placeholder-gray-600"
                    />
                  </div>
                  <label className="flex items-center gap-2 cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={editPadLength === 2}
                      onChange={(e) => setEditPadLength(e.target.checked ? 2 : 1)}
                      className="rounded"
                    />
                    <span className="text-xs text-gray-400">Double Pad (Switch-Lite/Diswoe)</span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={editTr2IsStart}
                      onChange={(e) => setEditTr2IsStart(e.target.checked)}
                      className="rounded"
                    />
                    <span className="text-xs text-gray-400">Use ZR/TR2 as Start button</span>
                  </label>
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
                    <button
                      onClick={() => deleteProfile(profile.unique_id)}
                      className="px-3 py-1 text-xs bg-red-600 rounded hover:bg-red-500 ml-auto"
                    >
                      Delete
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
                    {resolveMac(profile) !== profile.unique_id && resolveMac(profile) && (
                      <div className="text-xs text-gray-500 font-mono">MAC: {resolveMac(profile)}</div>
                    )}
                    {profile.guid_override && (
                      <div className="text-xs text-yellow-500 font-mono">GUID: {profile.guid_override}</div>
                    )}
                    <div className="flex gap-3 mt-1">
                      {profile.pad_length === 2 && (
                        <div className="text-[10px] text-purple-400 uppercase font-bold tracking-tighter">Double Pad</div>
                      )}
                      {profile.tr2_is_start && (
                        <div className="text-[10px] text-blue-400 uppercase font-bold tracking-tighter">Start: ZR/TR2</div>
                      )}
                    </div>
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
