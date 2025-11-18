from datetime import datetime
import operator

import json
import re
import shutil
import sys
import os
import ffmpy

import requests

import selenium
import selenium.common.exceptions
from selenium.webdriver import Chrome,Firefox,Edge
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException

import logging
from slugify import slugify
import urllib3.util

from .course import (EchoCourse,EchoCloudCourse,EchoVideos,EchoCloudVideos,_LOGGER)
from .videos import EchoVideos, EchoCloudVideos,EchoCloudSubVideo,EchoVideo
from .echo_exceptions import NotVideoError

from .hls_downloader import Downloader
from .naive_m3u8_parser import NaiveM3U8Parser

class MediaURL:
    def __init__(self, url,mediaType,isHls,isLive,qualities=None):
        self.url = url
        self.mediaType = mediaType
        self.isHls = isHls
        self.isLive = isLive
        self.qualities = qualities
        

def update_collection_retrieval_progress(current, total):
    prefix = ">> Retrieving echo360 Collection Info... "
    status = "{}/{} videos".format(current, total)
    text = "\r{0} {1} ".format(prefix, status)
    sys.stdout.write(text)
    sys.stdout.flush()

class EchoCloudCollection(EchoCourse):
    def __init__(self, uuid, hostname=None, alternative_feeds=False):
        self._course_id = uuid
        self._course_name = None
        self._uuid = uuid
        self._videos = None
        self._driver:Chrome|Firefox = None
        self._alternative_feeds = alternative_feeds
        if hostname is None:
            self._hostname = "https://echo360.org.uk/"
        else:
            self._hostname = hostname
        self._hostname = self._hostname.rstrip("/")

    def get_videos(self):
        if self._driver is None:
            raise Exception("webdriver not set yet!!!", "")
        if not self._videos:
            try:
                course_data_json = self._get_course_data()
                videos_json = course_data_json
                self._videos = EchoCloudCollectionVideoGroups(
                    videos_json["data"], self._driver, self.hostname, self._alternative_feeds
                )
            except selenium.common.exceptions.NoSuchElementException as e:
                print("selenium cannot find given elements")
                raise e

        return self._videos
    
    @property
    def videos(self):
        return self._videos or []

    @property
    def video_url(self):
        sts= re.sub("(https?):/*","\\1://","{}/api/ui/groups/{}".format(self._hostname, self._uuid).replace("//","/").strip())
        print(sts)
        return sts
    @property
    def course_id(self):
        if self._course_id is None:
            self._course_id = ""
        return self._course_id

    @property
    def course_name(self):
        if self._course_name is None:
            for v in self.course_data["data"]:
                try:
                    self._course_name:str = str(v["title"])
                    break
                except KeyError:
                    pass
            if self._course_name is None:
                # no available course name found...?
                self._course_name = "[[UNTITLED_COLLECTION]]"
        return self._course_name

    @property
    def nice_name(self):
        # Slugify to meet web Standards
        return slugify(self.course_name,lowercase=False,separator="_")

    def _get_course_data(self):
        try:
            self.driver.get(self.video_url)
            
            _LOGGER.debug(
                "Dumping course page at %s: %s",
                self.video_url,
                self._driver.page_source,
            )
            # use requests to retrieve data
            session = requests.Session()
            # load cookies
            for cookie in self.driver.get_cookies():
                session.cookies.set(cookie["name"], cookie["value"])

            r = session.get(self.video_url)
            if not r.ok:
                raise Exception("Error: Failed to get m3u8 info for EchoCourse!")

            json_str = r.text
        except ValueError as e:
            raise Exception("Unable to retrieve JSON (course_data) from url", e)
        except json.JSONDecodeError as e:
            print("failed to get a json")
        self.course_data = json.loads(json_str)
        return self.course_data




    
    
    
class EchoCloudCollectionVideoGroups(EchoVideos):
    def __init__(
        self, videos_json:list[dict], driver:"Chrome|Edge", hostname:str, alternative_feeds:bool, skip_video_on_error:bool=True
    ):
        assert videos_json is not None
        
        self._driver = driver
        self._videos = []
        total_videos_num = len(videos_json)
        update_collection_retrieval_progress(0, total_videos_num)

        for i, video_json in enumerate(videos_json):
            try:
                self._videos.extend(
                    EchoCloudCollectionVideos(
                        video_json["content"], self._driver, hostname, alternative_feeds, video_json["id"]
                    ).videos
                )
            except Exception as err:
                if not skip_video_on_error:
                    raise
            update_collection_retrieval_progress(i + 1, total_videos_num)

        self._videos.sort(key=operator.attrgetter("date"))

    @property
    def videos(self):
        return self._videos
    

class EchoCloudCollectionVideos(EchoVideos):
    def __init__(
        self, videos_json:list[dict], driver:"Chrome|Edge", hostname:str, alternative_feeds:bool, collection_id, skip_video_on_error:bool=True
    ):
        assert videos_json is not None
        self._driver = driver
        self._videos = []
        total_videos_num = len(videos_json)
        
        update_collection_retrieval_progress(0, total_videos_num)

        for i, video_json in enumerate(videos_json):
            try:
                self._videos.append(
                    EchoCloudCollectionVideo(
                        video_json, self._driver, hostname, alternative_feeds, collection_id
                    )
                )
            except NotVideoError as e:
                continue
            except Exception as err:
                if not skip_video_on_error:
                    raise
            update_collection_retrieval_progress(i + 1, total_videos_num)

        self._videos.sort(key=operator.attrgetter("date"))

    @property
    def videos(self):
        return self._videos


class EchoCloudCollectionVideo(EchoVideo):
    
    # TODO: Cach JSON to reduce network load
    @property
    def video_url(self):
        return "{}/api/ui/groups/{}/media/{}".format(self.hostname, self.collection_id,self.video_id)
    
    @property
    def date(self)->datetime:
        return self._date

    def __init__(self, video_json:dict[str], driver:Chrome|Firefox, hostname:str , alternative_feeds:bool, collection_id:str,**kwargs):
        
        if(str(video_json["mediaType"]).strip().lower()!="video"):
            raise NotVideoError("Not a Video")
        
        self.hostname= hostname
        self._driver = driver
        self.video_json = video_json
        self._video_id =str(video_json["id"])
        self.is_multipart_video = False
        self.sub_videos = [self]
        self.download_alternative_feeds = alternative_feeds
        
        

        video_id = "{0}".format(video_json["id"])
        self.video_id = str(video_id)  # cast back to string
        
        self.collection_id = str(collection_id)

        self._driver.get(self.video_url)
        _LOGGER.debug(
            "Dumping video page at %s: %s", self.video_url, self._driver.page_source
        )

        m3u8_url = self._loop_find_m3u8_url(self.video_url, waitsecond=30)
        
        _LOGGER.debug("Found the following urls %s", m3u8_url)
        self._url = m3u8_url

        self._date = self.get_date(video_json)
        self._title = video_json["title"]

    def download(self, output_dir, filename, pool_size=50):
        print("")
        
        if(sys.stdout.isatty()):
            col =shutil.get_terminal_size((60,24)).columns
        else:
            col=60
            
        print("-" * col)
        print('Downloading "{}"'.format(filename))
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        session = requests.Session()
        # load cookies
        for cookie in self._driver.get_cookies():
            session.cookies.set(cookie["name"], cookie["value"])

        urls = self.url
        if not isinstance(urls, list):
            urls = [urls]

        if not self.download_alternative_feeds:
            # download_alternative_feeds defaults to False, slice to include only the first one
            urls = urls[:1]

        final_result = True
        for counter, single_url in enumerate(urls):
            if self.download_alternative_feeds:
                print("- Downloading video feed {}...".format(counter + 1))
            new_filename = (
                (f"{str(filename).stip()}_{str(counter + 1)}")
                if self.download_alternative_feeds
                else filename
            )
            result = self.download_single(
                session, single_url, output_dir, new_filename, pool_size
            )
            final_result = final_result and result

        return final_result

    def download_single(self, session:requests.Session, single_url:str, output_dir:str, filename:str, pool_size:int):
        if os.path.exists(os.path.join(output_dir, filename + ".mp4")):
            print(" > Skipping downloaded video")
            print("-" * 60)
            return True

        fname= urllib3.util.parse_url(single_url).path
        fname
        if fname.endswith(".m3u8"):
            r = session.get(single_url)
            if not r.ok:
                print("Error: Failed to get m3u8 info. Skipping this video")
                return False

            lines = [n for n in r.content.decode().split("\n")]
            m3u8_video = None
            m3u8_audio = None

            _LOGGER.debug("Searching for m3u8 with content {}".format(lines))

            m3u8_parser = NaiveM3U8Parser(lines)
            
            try:
                m3u8_parser.parse()
            except Exception as e:
                _LOGGER.debug("Exception occurred while parsing m3u8: {}".format(e))
                print("Failed to parse m3u8. Skipping...")
                return False

            m3u8_video, m3u8_audio = m3u8_parser.get_video_and_audio()

            if (
                m3u8_video is None
            ):  # even if audio is None it's okay, maybe audio is include with video
                print("ERROR: Failed to find video m3u8... skipping this one")
                return False
            # NOW we can finally start downloading!
            from .hls_downloader import urljoin

            audio_file = None
            if m3u8_audio is not None:
                print("  > Downloading audio:")
                audio_file = self._download_url_to_dir(
                    urljoin(single_url, m3u8_audio),
                    output_dir,
                    filename + "_audio",
                    pool_size,
                    convert_to_mp4=False,
                )
            print("  > Downloading video:")
            video_file = self._download_url_to_dir(
                urljoin(single_url, m3u8_video),
                output_dir,
                filename + "_video",
                pool_size,
                convert_to_mp4=False,
            )
            sys.stdout.write("  > Converting to mp4... ")
            sys.stdout.flush()

            # combine audio file with video (separate audio might not exists.)
            if self.combine_audio_video(
                audio_file=audio_file,
                video_file=video_file,
                final_file=os.path.join(output_dir, filename + ".mp4"),
            ):
                # remove left-over plain audio/video files. (if mixing was successful)
                if audio_file is not None:
                    os.remove(audio_file)
                os.remove(video_file)

        else:  # ends with mp4
            import tqdm

            r = session.get(single_url, stream=True)
            total_size = int(r.headers.get("content-length", 0))
            block_size = 1024  # 1 kilobyte
            with tqdm.tqdm(total=total_size, unit="iB", unit_scale=True) as pbar:
                with open(os.path.join(output_dir, filename + ".mp4"), "wb") as f:
                    for data in r.iter_content(block_size):
                        pbar.update(len(data))
                        f.write(data)

        print("Done!")
        print("-" * 60)
        return True

    @staticmethod
    def combine_audio_video(audio_file, video_file, final_file):
        if os.path.exists(final_file):
            os.remove(final_file)
        _inputs = {}
        _inputs[video_file] = None
        if audio_file is not None:
            _inputs[audio_file] = None
        try:
            ff = ffmpy.FFmpeg(
                global_options="-loglevel panic",
                inputs=_inputs,
                outputs={
                    final_file: ["-c:v", "copy", "-c:a", "ac3"]
                    },
            )
            ff.run()
        except ffmpy.FFExecutableNotFoundError:
            print(
                '[WARN] Skipping mixing of audio/video because "ffmpeg" not installed.'
            )
            return False
        except ffmpy.FFRuntimeError:
            print(
                "[Error] Skipping mixing of audio/video because ffmpeg exited with non-zero status code."
            )
            return False
        return True

    def _loop_find_m3u8_url(self, video_url, waitsecond=15, max_attempts=5):
        
        def brute_force_get_url(*args,**kwargs):
            # this is the first method I tried, which sort of works
            stale_attempt = 1
            refresh_attempt = 1
            while True:
                self._driver.get(video_url)
                session = requests.Session()
                for cookie in self._driver.get_cookies():
                    session.cookies.set(cookie["name"], cookie["value"])

                r = session.get(self.video_url)
                if not r.ok:
                    raise Exception("Error: Failed to get m3u8 info for EchoCourse!")
                
                try:
                    dats =json.loads(r.text.replace("\\/", "/")),
                    data=dats[0]["data"]
                    urls:list[MediaURL] =[]
                    for data_ in data:
                        playbackInfo:dict[str] = data_["playbackInfo"]['audioVideo']
                        playables:list[dict] = playbackInfo.get("playableMedias")
                        if(playables is None):
                            return []
                        
                        for playable in playables:
                            isHls:bool =  playable["isHls"]
                            isLive:bool =  playable["isLive"]
                            mediaUrl = playable["uri"]
                            trackType = playable["trackType"]
                            quality = playable.get("quality")
                            urls+=[MediaURL(mediaUrl,trackType,isHls,isLive,quality)]
                        return urls

                except selenium.common.exceptions.TimeoutException:
                    if refresh_attempt >= max_attempts:
                        print(
                            "\r\nERROR: Connection timeouted after {} second for {} attempts... \
                              Possibly internet problem?".format(
                                waitsecond, max_attempts
                            )
                        )
                        raise
                    refresh_attempt += 1
                except StaleElementReferenceException:
                    if stale_attempt >= max_attempts:
                        print(
                            "\r\nERROR: Elements are not stable to retrieve after {} attempts... \
                            Possibly internet problem?".format(
                                max_attempts
                            )
                        )
                        raise
                    stale_attempt += 1

        def brute_force_get_mp4_url():
            """Forcefully try to find all .mp4 url in the page source"""
            urls = brute_force_get_url()
            if len(urls) == 0:
                raise Exception("None were found.")
            # in many cases, there would be urls in the format of http://xxx.{hd1,hd2,sd1,sd2}
            # I'm not sure what does the 1 and 2 in hd1,hd2 stands for, but hd and sd should means
            # high or low definition.
            # Some university uses hd1 and hd2 for their alternative feeds, use flag `-a`
            # to download both feeds.
            # Let's prioritise hd over sd, and 1 over 2 (the latter is arbitary)
            # which happens to be the natual order of letter anyway, so we can simply use sorted.
            return sorted(urls,key=lambda x : x.url)[:3]



        # try different methods in series, first the preferred ones, then the more
        # obscure ones.
        
        
        try:
            _LOGGER.debug("Trying brute_force_all_mp4 method")
            return [i.url for i in brute_force_get_mp4_url() if "video" in [k.lower() for k in i.mediaType]]
        except Exception as e:
            _LOGGER.debug("Encountered exception: {}".format(e))
        try:
            _LOGGER.debug("Trying brute_force_all_m3u8 method")
            m3u8urls = [i.url for i in brute_force_get_url() if "video" in [k.lower() for k in i.mediaType]]
            return m3u8urls
        except Exception as e:
            _LOGGER.debug("Encountered exception: {}".format(e))
            _LOGGER.debug("All methods had been exhausted.")
            print("Tried all methods to retrieve videos but all had failed!")
            raise

    def _extract_date(self, video_json):
        if self.is_multipart_video:
            if video_json["groupContent"]["createdDate"] is not None:
                return video_json["groupContent"]["createdDate"]

        if "startTimeUTC" in video_json["lesson"]:
            if video_json["lesson"]["startTimeUTC"] is not None:
                return video_json["lesson"]["startTimeUTC"]
        if "createdAt" in video_json["lesson"]["lesson"]:
            return video_json["lesson"]["lesson"]["createdAt"]

    def get_all_parts(self):
        return self.sub_videos