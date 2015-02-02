#
# iPlayercast
# Copyright 2013 Oscar Key
#

#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

from optparse import OptionParser
from configparser import RawConfigParser
import os
import re
import pickle
import subprocess
import datetime
import shutil
import json

# internal classes
class Programme:
	def __init__(self):
		self.pid = None
		self.name = None
		self.episode = None
		self.desc = None
		self.downloaded = False
		self.filename = None
		self.date_loaded = datetime.datetime.now()

	def calc_pid(self):
		p = re.compile('(\w+)\.m4a')
		m = p.match(self.filename)
		if m:
			new_pid = m.group(1)
			if new_pid != self.pid:
				print("=== pid not ok ===: " + self.pid + " != " + new_pid )
			return new_pid
		else:
			print("pid not found in file: " + self.filename)
			return "???"

	def fixup_file(self):
		if self.calc_pid() != self.pid:
			self.filename = self.pid + ".m4a"

class Feed:
	def __init__(self):
		self.programmes = []

# constants
MASTER_CONFIG_FILENAME   = "iplayercast.conf"
FEED_CONFIG_DIRECTORY    = "/feeds"
TEMP_DIRECTORY           = "/tmp/iplayercast/"
PROGRAMME_OUTPUT_KEYWORD = "programmeoutput"

# global variables
config_directory = None
master_config = None
get_iplayer_path = "get-iplayer"
bbc_programmes = []

def main():
	# parse the command line arguments, get the config file
	usage_string = "usage: python3 iplayercast -c [config directory]"
	parser = OptionParser(usage=usage_string)
	parser.add_option("-c", "--config-dir", action="store", type="string", dest="config",
						metavar="DIR", help="DIRECTORY to search for configs")
	(options, args) = parser.parse_args()

	# check we have the required argument
	global config_directory
	config_directory = options.config
	if not options.config:
		config_directory = "./"
	run()  # do the stuff

def run():
	# load the config file
	global master_config
	master_config = RawConfigParser()
	master_config.read(config_directory + MASTER_CONFIG_FILENAME)

	# set the get-iplayer path
	global get_iplayer_path
	if master_config.has_option("General", "get-iplayer_path"):
		get_iplayer_path = master_config.get("General", "get-iplayer_path")

	# refresh the get-iplayer cache
	# print("Refreshing get-iplayer... (this may take some time)")
	# subprocess.check_output([get_iplayer_path, "--type=all", "--quiet"])

	# new BBC rules :-( now we get the programm info externally using a different script
	# and read that scripts output directly into a hash
	global bbc_programmes
	bbc_programmes = load_bbc_programmes()

	# scan for feed config files and process each
	for root, directories, files in os.walk(config_directory + FEED_CONFIG_DIRECTORY):
		for filename in files:
			if filename == ".DS_Store":
				continue

			print("about to read config " + filename )
			load_feed(filename)
		print("Finished.")
		return # stop here, we have processed the feeds

	# if we have not returned at this point, then no config directory was found, this is a problem
	print("No config directory found")

def load_bbc_programmes():
	genres = [ 'entertainment', 'comedy', 'drama' ]
	result = []

	for genre in genres:
		result += load_bbc_genre(genre)

	return result

def load_bbc_genre(genre):
	print("loading programmes for genre" + genre)
	filename = "json/" + genre + ".json"
	data =  open(filename)
	p = json.load(data)
	flat_p = [y for x in p for y in x]
	data.close()
	print("loaded " + str(len(flat_p)) + " programmes for genre " + genre)

	return flat_p

def load_feed(config_filename):
	# load the feed config file
	feed_config = RawConfigParser()
	feed_config.read(config_directory + FEED_CONFIG_DIRECTORY + "/" + config_filename)
	print("=== Loading feed: " + feed_config.get("General", "name"))

	# create the output directory for this feed if required
	make_sure_path_exists(master_config.get("General", "output_dir") + "/" + feed_config.get("General", "output_dir"))

	# initialize the feed from the history
	feed = load_feed_history(feed_config)

	# split the search terms into a list
	searches = feed_config.get("General", "searches").split(",")
	# loop and retrieve details for each search using get-iplayer, insert it into the feed if not already present
	for search in searches:
		print("search program " + search )
		programmes = get_programmes(search.strip())

		# check if the feed already contains each programme, if not add it
		for new_programme in programmes:
			print("  found program " + new_programme.name )
			present = False
			for old_programme in feed.programmes:
				if new_programme.pid == old_programme.pid:
					print("  program was already present (" + new_programme.name + ")")
					present = True
			# add the programme if not present
			if not present:
				print("  ** adding program " + new_programme.name )
				feed.programmes.append(new_programme)

	# download any programme that has not already been downloaded
	for programme in feed.programmes:
		if not programme.downloaded:
			print("downloading program " + programme.name )
			download_programme(feed_config, programme)

	# save the feed history
	save_feed_history(feed, feed_config)

	# write the feed rss
	write_feed_rss(feed_config, feed)


def load_feed_history(feed_config):
	history_file_path = master_config.get("General", "output_dir") + "/" + feed_config.get("General", "output_dir") + "/history"
	try:
		history_file = open(history_file_path, "rb")
		feed = pickle.load(history_file)
		history_file.close()
		return feed
	except IOError:
		print("History for \"" + feed_config.get("General", "name") + "\" did not exist or some other problem occured. Will create one.")
		return Feed()
		print("history created")


def save_feed_history(feed, feed_config):
	# open the history file and save the feed as json into it
	feed_history_file = master_config.get("General", "output_dir") + "/" + feed_config.get("General", "output_dir") + "/history"
	try:
		history_file = open(feed_history_file, "wb")
		pickle.dump(feed, history_file)
		history_file.close()
	except IOError as exception:
		print("Could not save history file for \"" + feed_config.get("General", "name") + "\"")
		print(exception)


def get_programmes(title):
	global bbc_programmes
	checker  = re.compile( title, re.IGNORECASE )
	programmes = []

	for p in bbc_programmes:
		if checker.search(p['title']):
			print("  found program " + p['title'] + " with pid " + p['pid'])
			programme = Programme()
			programme.pid = p['pid']
			programme.name = p['title']
			programme.episode = p['episode']
			programme.desc = p['desc']
			programmes.append(programme)
	return programmes

def get_programmes_old(search):
	# build the command line switches
	switch_type = "--type=radio"
	switch_output_control = "--nocopyright"
	switch_list_format = "--listformat=" + PROGRAMME_OUTPUT_KEYWORD + "|<pid>|<name>|<episode>|<desc>"

	# run the command
	output = subprocess.check_output([get_iplayer_path, switch_type, switch_output_control, switch_list_format, search]).decode("utf-8", 'ignore')

	# build this output into programme objects, produce a list of the output lines
	programmes = []
	lines = output.split("\n")
	# pick the lines that start with the keyword
	for line in lines:
		parts = line.split("|")
		if parts[0] == PROGRAMME_OUTPUT_KEYWORD:
			programme = Programme()
			programme.pid = parts[1]
			programme.name = parts[2]
			programme.episode = parts[3]
			programme.desc = parts[4]
			programmes.append(programme)

	# return the resulting array
	return programmes


def download_programme(feed_config, programme):
	# report what is going on
	print("Downloading episode \"" + programme.episode + "\" of \"" + programme.name + "\"")

	# run get-iplayer telling it to save to the correct dir with the pid as the name
	switch_output_dir  = "--output=" + TEMP_DIRECTORY
	switch_file_prefix = "--file-prefix=<pid>"
	switch_type        = "--type=all"
	switch_get         = "--pid=" + programme.pid
	switch_thumb       = "--thumb"

	# check if we need to switch tagging off
	switch_tagging = ""
	if(master_config.getboolean("General", "no_file_tagging")):
		switch_tagging = "--no-tag"
	# "--quiet",
	command = [get_iplayer_path, switch_output_dir, switch_file_prefix, switch_type, switch_get, switch_thumb, "--force", "--modes=best", switch_tagging]
	subprocess.call(command)

	# find and record the name of the programme, and then move it to the final directory
	output_dir = master_config.get("General", "output_dir") + "/" + feed_config.get("General", "output_dir")
	for root, directories, files in os.walk(TEMP_DIRECTORY):
		for filename in files:
			programme.filename = filename
			print("-- moving "+ filename + " from " + TEMP_DIRECTORY + " to " + output_dir )
			print("-- pid: " + programme.pid);
			# os.rename(TEMP_DIRECTORY + filename, output_dir + "/" + filename)
			shutil.move(TEMP_DIRECTORY + filename, output_dir + "/" + filename)

	# delete the temp directory
	os.rmdir(TEMP_DIRECTORY)

	# mark the programme as download so it is not downloaded again
	programme.downloaded = True


def make_sure_path_exists(path):
	try:
		os.makedirs(path)
	except OSError:
		pass

def write_feed_rss(feed_config, feed):
	feed_path = master_config.get("General", "output_dir") + "/" + feed_config.get("General", "output_dir") + "/"
	output_file_path = feed_path + "/feed.xml"
	output_file = open(output_file_path, "w")
	now = datetime.datetime.now()
	rss_link = master_config.get("General", "server_url") + "/" + feed_config.get("General", "output_dir") + "/" + "/feed.xml"
	rss_ttl  = "60"  # time to live in minutes ?

	# write header information
	output_file.write("<?xml version=\"1.0\" encoding=\"UTF-8\" ?>\n")
	output_file.write("<rss xmlns:itunes=\"http://www.itunes.com/dtds/podcast-1.0.dtd\" version=\"2.0\">\n")
	output_file.write("<channel>\n")
	output_file.write("<title>" + feed_config.get("General", "name") + "</title>\n")
	output_file.write("<description>" + "iplayercast custom feed" + "</description>\n")
	output_file.write("<link>" + rss_link + "</link>\n")
	output_file.write("<ttl>" + rss_ttl + "</ttl>\n")
	#output_file.write("<image><url>" + rssImageUrl + "</url><title>" + rssTitle + "</title><link>" + rss_link + "</link></image>\n")
	#output_file.write("<copyright>BBC 2013</copyright>\n")
	output_file.write("<lastBuildDate>" + format_date(now) + "</lastBuildDate>\n")
	output_file.write("<pubDate>" + format_date(now) + "</pubDate>\n")
	#output_file.write("<webMaster>" + rssWebMaster + "</webMaster>\n")

	# loop and write each programme to the feed
	for programme in feed.programmes:
		programme.fixup_file()

		# find the file size
		file_size = "1024"
		try:
			file_size = str(os.path.getsize(feed_path + programme.filename))
		except OSError:
			print("Programme file appears to be missing for \"" + programme.name + "\": " + feed_path + programme.filename)

		file_url  = master_config.get("General", "server_url") + "/" + feed_config.get("General", "output_dir") + "/" + programme.filename
#		image_name = os.path.splitext(programme.filename)[0] + ".jpg"
#		image_url = master_config.get("General", "server_url") + "/" + feed_config.get("General", "output_dir") + "/" + image_name
		output_file.write("<item>\n")
		output_file.write("<title>" + programme.episode + " - " + programme.name + "</title>\n")
		output_file.write("<description>" + programme.desc + "</description>\n")
		#output_file.write("<link>" + rssItemURL + relativePath + "</link>\n")
		output_file.write("<guid>" + programme.pid + "</guid>\n")
		output_file.write("<pubDate>" + format_date(programme.date_loaded) + "</pubDate>\n")
		output_file.write("<enclosure url=\"" + file_url + "\" length=\"" + file_size + "\" type=\"" + get_extension(file_url) + "\" />\n")
#		output_file.write("<itunes:image href=\"" + image_url + "\"></itunes:image>\n")
#		output_file.write("<image>\n")
#		output_file.write("<url>" + image_url + "</url>\n")
#		output_file.write("</image>\n")
		output_file.write("</item>\n")

	# write footer
	output_file.write("</channel>\n")
	output_file.write("</rss>")
	output_file.close()
	print("Feed for \"" + feed_config.get("General", "name") + "\" written")

def format_date(date):
	return date.strftime("%a, %d %b %Y %H:%M:%S +0000")

def get_extension(filename):
	split = filename.split(".")
	return split[split.__len__() - 1]

# catch this module being run directly
if __name__ == "__main__":
	main()
