import sys
import os

# Add local_video_factory to sys.path so its modules can be loaded properly
repo_root = os.path.dirname(os.path.abspath(__file__))
lvf_dir = os.path.join(repo_root, "local_video_factory")
if lvf_dir not in sys.path:
    sys.path.insert(0, lvf_dir)
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

# Import the main plugin class so it is exposed at the module level
from local_video_factory.plugins.local_video_factory_plugin.plugin import LocalVideoFactoryPlugin
