# The common titles and supported extensions,
# as defined by https://github.com/github/markup
SUPPORTED_TITLES = ['README', 'Readme', 'readme', 'Home']
SUPPORTED_EXTENSIONS = ['.md', '.markdown']


# The default filenames when no file is provided
DEFAULT_FILENAMES = [title + ext
                     for title in SUPPORTED_TITLES
                     for ext in SUPPORTED_EXTENSIONS]
DEFAULT_FILENAME = DEFAULT_FILENAMES[0]


# The default directory to load Grip settings from
DEFAULT_GRIPHOME = '~/.grip'


# The default URL of the Grip server
DEFAULT_GRIPURL = '/__/grip'
