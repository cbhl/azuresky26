## michael-chang.ca (2026 edition)

&copy; 2013-2026 Michael Chang

Hi, I'm Michael. I've been coding since I was eight, but in terms of full-time experience I've been doing this for ten years.

This is the source code for my personal website, a static site that can be built with Zola.

If you're looking for my resume, you should be able to find it rendered at https://michael-chang.ca/resume/.

### Install Zola

```
brew install zola
```

On other platforms, use https://www.getzola.org/documentation/getting-started/installation/.

### Preview

```
zola serve
```

Then open http://127.0.0.1:1111/.

### Build

```
zola build
```

### Deploy

After running `zola build`, rsync the contents of `public/` to the static web host of your choice.

```
./deploy.sh
```

### Why Zola?

I got tired of updating Ruby deps on my old static website repo, especially
since I didn't use Ruby much professionally in my professional work (only for a
few weeks in one co-op term), so trying another thing 13 years later. I looked
at jamstack.org, as one does, to see what was out there. Despite being fond of
Golang, Hugo felt a bit too heavyweight... so trying Zola now (especially since
I feel like I'm reading a lot more about Rust than Golang these days).

