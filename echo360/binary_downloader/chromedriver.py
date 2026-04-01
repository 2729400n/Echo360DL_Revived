from .downloader import BinaryDownloader


class ChromedriverDownloader(BinaryDownloader):
    _os_linux_32 = "linux32"
    _os_linux_64 = "linux64"
    _os_windows_32 = "win32"
    _os_windows_64 = "win32"
    _os_darwin_32 = "mac64"
    _os_darwin_64 = "mac64"
    _os_darwin_arm = "mac_arm64"
    def __init__(self):
        self._name = "chrome"
        #https://storage.googleapis.com/chrome-for-testing-public/146.0.7637.0/chrome-win32.zip
        #https://storage.googleapis.com/chrome-for-testing-public/146.0.7637.0/win32/chrome-win32.zip
        self._download_link_root = "https://storage.googleapis.com/chrome-for-testing-public"
        self._version = "146.0.7637.0"

    def get_os_suffix(self):
        
        return super(ChromedriverDownloader, self).get_os_suffix()

    def get_download_link(self):
        os_suffix = self.get_os_suffix()
        filename = "chrome-{0}.zip".format(os_suffix)
        download_link = "{0}/{1}/{3}/{2}".format(
            self._download_link_root, self._version, filename,os_suffix
        )
        print('Downlaod link',download_link)
        return download_link, filename

    def get_bin_root_path(self):
        return super(ChromedriverDownloader, self).get_bin_root_path()

    def get_bin(self):
        os_suffix = self.get_os_suffix()
        extension = ".exe" if "win" in self.get_os_suffix() else ""
        return "{0}/chrome-{3}/{1}{2}".format(self.get_bin_root_path(), self._name, extension,os_suffix)

    def download(self):
        super(ChromedriverDownloader, self).download()
