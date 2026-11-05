export type Engine = {
  id: 'landslide' | 'glacier' | 'known-place' | 'river-shift';
  name: string;
  status: 'AVAILABLE' | 'RESEARCH PREVIEW' | 'SETUP REQUIRED';
  description: string;
  actionLabel: string;
  image: string;
  icon: 'landslide' | 'glacier' | 'known-place' | 'river';
};

export const engines: Engine[] = [
  {
    id: 'landslide',
    name: 'Landslide',
    status: 'AVAILABLE',
    description: 'Screen the full area for spatial change candidates, then inspect only measurements supported by the observations.',
    actionLabel: 'Open area analysis',
    image: 'https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?auto=format&fit=crop&w=900&q=88',
    icon: 'landslide',
  },
  {
    id: 'glacier',
    name: 'Glacier Movement',
    status: 'AVAILABLE',
    description: 'Use the same AOI-wide displacement workflow to examine surface-change evidence across glacier terrain.',
    actionLabel: 'Explore glacier terrain',
    image: 'https://images.unsplash.com/photo-1454496522488-7a8e488e8606?auto=format&fit=crop&w=900&q=88',
    icon: 'glacier',
  },
  {
    id: 'known-place',
    name: 'Known Place Analysis',
    status: 'AVAILABLE',
    description: 'Choose an outer AOI and date window, then define separate Measurement and Reference polygons for focused GOFF analysis.',
    actionLabel: 'Select AOI and draw two polygons',
    image: 'https://images.unsplash.com/photo-1519681393784-d120267933ba?auto=format&fit=crop&w=900&q=88',
    icon: 'known-place',
  },
  {
    id: 'river-shift',
    name: 'River Shift',
    status: 'AVAILABLE',
    description: 'Explore eligible river reaches across the global NISAR L-band observation footprint. Discover compatible GCOV acquisitions and review observed-date water and persistent land–water change candidates with source provenance.',
    actionLabel: 'Open River Shift engine',
    image: 'https://images.unsplash.com/photo-1437482078695-73f5ca6c96e2?auto=format&fit=crop&w=900&q=88',
    icon: 'river',
  },
];
