'use client';

import { useState, useEffect, useRef } from 'react';
import { newsApi, RSSFeed } from '@/lib/api';
import { Settings, Plus, X } from 'lucide-react';

interface FeedManagerProps {
  selectedFeeds: string[];
  onFeedSelectionApply: (feeds: string[]) => void;
}

const CATEGORY_OPTIONS = ['Tech', 'Global News', 'Vietnamese News', 'US News'];

export default function FeedManager({ selectedFeeds, onFeedSelectionApply }: FeedManagerProps) {
  const [feeds, setFeeds] = useState<RSSFeed[]>([]);
  const [loading, setLoading] = useState(true);
  const [showSelector, setShowSelector] = useState(false);
  const [localSelection, setLocalSelection] = useState<string[]>(selectedFeeds);
  const [applying, setApplying] = useState(false);
  const [showAddForm, setShowAddForm] = useState(false);
  const [adding, setAdding] = useState(false);
  const [newFeed, setNewFeed] = useState({ name: '', url: '', category: 'Tech' });
  const selectorRef = useRef<HTMLDivElement>(null);

  const hasInitializedRef = useRef(false);

  useEffect(() => {
    loadFeeds();
  }, []);

  useEffect(() => {
    // Sync localSelection with parent when feeds load or selectedFeeds change.
    // When selectedFeeds is empty, backend means "all feeds" — show all as selected in UI only; do not call onFeedSelectionApply (avoids redundant API request).
    if (feeds.length > 0 && !hasInitializedRef.current) {
      if (selectedFeeds.length === 0) {
        setLocalSelection(feeds.map(feed => feed.name));
      } else {
        setLocalSelection(selectedFeeds);
      }
      hasInitializedRef.current = true;
    } else if (hasInitializedRef.current) {
      setLocalSelection(selectedFeeds.length > 0 ? selectedFeeds : feeds.map(feed => feed.name));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [feeds, selectedFeeds]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (selectorRef.current && !selectorRef.current.contains(event.target as Node)) {
        setShowSelector(false);
      }
    };

    if (showSelector) {
      document.addEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [showSelector]);

  const loadFeeds = async () => {
    try {
      setLoading(true);
      const feedsData = await newsApi.getFeeds();
      setFeeds(feedsData);
    } catch (error) {
      console.error('Error loading feeds:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleAddFeed = async () => {
    if (!newFeed.name.trim() || !newFeed.url.trim()) {
      alert('Please fill in all required fields');
      return;
    }

    const feedName = newFeed.name.trim();
    const feedUrl = newFeed.url.trim();
    const feedCategory = newFeed.category;

    try {
      setAdding(true);
      await newsApi.addFeed({
        name: feedName,
        url: feedUrl.split(/[\s,]+/).filter(Boolean),
        category: feedCategory
      });
      
      // Reset form
      setNewFeed({ name: '', url: '', category: 'Tech' });
      setShowAddForm(false);
      
      // Reload feeds
      await loadFeeds();
      
      // Add the new feed to selection
      const updatedSelection = [...localSelection, feedName];
      setLocalSelection(updatedSelection);
      onFeedSelectionApply(updatedSelection);
    } catch (error: any) {
      console.error('Error adding feed:', error);
      alert(error.response?.data?.detail || 'Failed to add feed. Please try again.');
    } finally {
      setAdding(false);
    }
  };

  const handleFeedToggle = (feedName: string) => {
    setLocalSelection((prev) =>
      prev.includes(feedName)
        ? prev.filter(feed => feed !== feedName)
        : [...prev, feedName]
    );
  };

  const handleSelectAll = () => {
    const allFeedNames = feeds.map(feed => feed.name);
    setLocalSelection(allFeedNames);
  };

  const handleSelectNone = () => {
    setLocalSelection([]);
  };

  const handleApply = async () => {
    setApplying(true);
    try {
      await onFeedSelectionApply(localSelection);
      setShowSelector(false);
    } catch (err) {
      console.error(err);
    } finally {
      setApplying(false);
    }
  };


  if (loading) {
    return (
      <div className="flex items-center justify-center p-4">
        <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-primary-600"></div>
        <span className="ml-2 text-sm text-gray-600 dark:text-gray-400">Loading feeds...</span>
      </div>
    );
  }

  return (
    <div className="relative px-2" ref={selectorRef}>
      <button
        onClick={() => setShowSelector(!showSelector)}
        className="flex items-center space-x-2 px-2 sm:px-4 py-2 bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-md hover:bg-gray-50 dark:hover:bg-gray-600 transition-colors"
      >
        <Settings className="h-4 w-4 text-gray-600 dark:text-gray-400" />
        <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
          Feeds ({selectedFeeds.length}/{feeds.length})
        </span>
      </button>

      {showSelector && (
        <div className="absolute top-full mt-1 w-80 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-md shadow-lg z-10" style={{ left: '-100%' }}>
          <div className="p-4 border-b border-gray-200 dark:border-gray-700">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium text-gray-900 dark:text-white">Select Feeds</h3>
              <div className="flex space-x-2">
                <button
                  onClick={handleSelectAll}
                  className="text-xs text-primary-600 dark:text-primary-400 hover:text-primary-700 dark:hover:text-primary-300"
                >
                  Select All
                </button>
                <button
                  onClick={handleSelectNone}
                  className="text-xs text-gray-600 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300"
                >
                  Clear
                </button>
              </div>
            </div>
            <div className="text-xs text-gray-500 dark:text-gray-400 mb-3">
              Selected feeds will be used to filter articles
            </div>
            {/* <button
              onClick={() => setShowAddForm(!showAddForm)}
              className="w-full flex items-center justify-center space-x-2 px-3 py-2 text-sm font-medium text-primary-600 dark:text-primary-400 bg-primary-50 dark:bg-primary-900/20 border border-primary-200 dark:border-primary-800 rounded-md hover:bg-primary-100 dark:hover:bg-primary-900/30 transition-colors"
            >
              <Plus className="h-4 w-4" />
              <span>Add New Feed</span>
            </button> */}
          </div>

          {showAddForm && (
            <div className="p-4 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900">
              <div className="flex items-center justify-between mb-3">
                <h4 className="text-sm font-medium text-gray-900 dark:text-white">Add New Feed</h4>
                <button
                  onClick={() => setShowAddForm(false)}
                  className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="space-y-3">
                <div>
                  <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Name
                  </label>
                  <input
                    type="text"
                    value={newFeed.name}
                    onChange={(e) => setNewFeed({ ...newFeed, name: e.target.value })}
                    placeholder="Feed name"
                    className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                    URL
                  </label>
                  <input
                    type="text"
                    value={newFeed.url}
                    onChange={(e) => setNewFeed({ ...newFeed, url: e.target.value })}
                    placeholder="RSS URLs separated by spaces or commas"
                    className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Category
                  </label>
                  <select
                    value={newFeed.category}
                    onChange={(e) => setNewFeed({ ...newFeed, category: e.target.value })}
                    className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                  >
                    {CATEGORY_OPTIONS.map((cat) => (
                      <option key={cat} value={cat}>
                        {cat}
                      </option>
                    ))}
                  </select>
                </div>
                {/* <button
                  onClick={handleAddFeed}
                  disabled={adding || !newFeed.name.trim() || !newFeed.url.trim()}
                  className="w-full px-3 py-2 text-sm font-medium bg-primary-600 text-white rounded-md hover:bg-primary-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {adding ? 'Adding...' : 'Add Feed'}
                </button> */}
              </div>
            </div>
          )}
          <div className="max-h-64 overflow-y-auto bg-white dark:bg-gray-800">
            {feeds.map((feed) => (
              <label
                key={feed.id}
                className="flex items-center p-3 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer border-b border-gray-100 dark:border-gray-700 last:border-b-0"
              >
                <input
                  type="checkbox"
                  checked={localSelection.includes(feed.name)}
                  onChange={() => handleFeedToggle(feed.name)}
                  className="h-4 w-4 text-primary-600 focus:ring-primary-500 border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-900"
                />
                <div className="ml-3 flex-1">
                  <span className="text-sm font-medium text-gray-900 dark:text-white">{feed.name}</span>
                </div>
              </label>
            ))}
          </div>
          <div className="flex justify-end p-2 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900">
            <button
              onClick={handleApply}
              disabled={applying || (localSelection.sort().join(',') === selectedFeeds.sort().join(','))}
              className={`px-2 py-1 rounded-md text-sm font-medium bg-primary-600 text-white hover:bg-primary-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed`}
            >
              {applying ? 'Applying...' : 'Apply'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
} 